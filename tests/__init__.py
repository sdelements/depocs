import threading
import unittest
from depocs import Scoped


class ScopedTests(unittest.TestCase):
    # TODO: Move out of this app

    # Subclassing

    def test_default_options(self):
        class Base(Scoped):
            pass

        class Sub(Base):
            pass

        self.assertEqual(16, Base.ScopedOptions.max_nesting)
        self.assertEqual(False, Base.ScopedOptions.allow_reuse)

        # Direct subclass of Scoped should get its own stack by default
        self.assertFalse(Base.ScopedOptions.inherit_stack)

        # All other ancestors should inherit their stack by default
        self.assertTrue(Sub.ScopedOptions.inherit_stack)

    def test_option_inheritance(self):
        class Sub(Scoped):
            class ScopedOptions:
                inherit_stack = False
                max_nesting = 3
                allow_reuse = True

        class SubSub(Sub):
            class ScopedOptions:
                pass

        # ScopedOptions should subclass the parent ScopedOptions and inherit its attributes
        self.assertTrue(SubSub.ScopedOptions, Sub.ScopedOptions)
        self.assertEqual(Sub.ScopedOptions.max_nesting, SubSub.ScopedOptions.max_nesting)
        self.assertEqual(Sub.ScopedOptions.allow_reuse, SubSub.ScopedOptions.allow_reuse)

        # except for inherit_stack, which should not be inherited
        self.assertTrue(SubSub.ScopedOptions.inherit_stack)

    def test_exceptions_automatically_subclassed(self):
        class Sub(Scoped):
            pass

        self.assertFalse(Sub.Missing == Scoped.Missing)
        self.assertTrue(issubclass(Sub.Missing, Scoped.Missing))

        self.assertFalse(Sub.LifecycleError == Scoped.LifecycleError)
        self.assertTrue(issubclass(Sub.LifecycleError, Scoped.LifecycleError))

    def test_cant_inherit_stack_from_root(self):
        def bad():
            class SO(Scoped):
                class ScopedOptions:
                    inherit_stack = True

        self.assertRaises(TypeError, bad)

    def test_cant_change_max_nesting_on_inherited_stack(self):
        def bad():
            class Base(Scoped):
                pass

            class Sub(Base):
                class ScopedOptions:
                    inherit_stack = True
                    max_nesting = 99

        self.assertRaises(TypeError, bad)

    def test_mixin_inheritance(self):
        class OtherBase(object):
            pass

        class SubA(Scoped, OtherBase):
            pass

        class SubB(OtherBase, Scoped):
            pass

    def test_diamond_inheritance(self):
        class SubA(Scoped):
            pass

        class SubB(Scoped):
            pass

        class SubAB(SubA, SubB):
            pass

    # Lifecycle

    def test_nothing_in_scope(self):
        class SO(Scoped):
            pass

        self.assertFalse(SO.has_current)
        self.assertRaises(SO.Missing, lambda: SO.current)

    def test_unused(self):
        class SO(Scoped):
            pass

        so = SO()

        self.assertFalse(so.is_used)
        self.assertFalse(so.is_open)
        self.assertFalse(so.is_current)
        self.assertFalse(SO.has_current)

    def test_open_and_close(self):
        class SO(Scoped):
            pass

        so = SO().open()

        self.assertTrue(so.is_used)
        self.assertTrue(so.is_open)
        self.assertTrue(so.is_current)
        self.assertTrue(SO.has_current)
        self.assertEqual(so, SO.current)

        so.close()

        self.assertTrue(so.is_used)
        self.assertFalse(so.is_open)
        self.assertFalse(so.is_current)
        self.assertFalse(SO.has_current)
        self.assertRaises(SO.Missing, lambda: SO.current)

    def test_context_manager(self):
        class SO(Scoped):
            pass

        with SO() as so:
            self.assertTrue(so.is_used)
            self.assertTrue(so.is_open)
            self.assertTrue(so.is_current)
            self.assertTrue(SO.has_current)
            self.assertEqual(so, SO.current)

        self.assertTrue(so.is_used)
        self.assertFalse(so.is_open)
        self.assertFalse(so.is_current)
        self.assertFalse(SO.has_current)
        self.assertRaises(SO.Missing, lambda: SO.current)

    def test_context_manager_exception_handling(self):
        class SO(Scoped):
            pass

        expectedError = RuntimeError()
        try:
            with SO():
                raise expectedError
        except RuntimeError as err:
            self.assertEqual(expectedError, err)
            self.assertFalse(SO.has_current)
        else:
            self.fail("Scoped object ate the exception")

    def test_reopen_raises(self):
        class SO(Scoped):
            pass

        with SO() as so:
            self.assertRaises(SO.LifecycleError, lambda: so.open())

    def test_close_unopened_raises(self):
        class SO(Scoped):
            pass

        self.assertRaises(SO.LifecycleError, lambda: SO().close())

    def test_close_non_current_raises(self):
        class SO(Scoped):
            class ScopedOptions:
                max_nesting = 2

        with SO() as outer:
            with SO():
                self.assertRaises(SO.LifecycleError, lambda: outer.close())

    # Re-use

    def test_reusable(self):
        class SO(Scoped):
            class ScopedOptions:
                allow_reuse = True

        so = SO()
        with so:
            pass
        with so:
            pass

    def test_non_reusable(self):
        class SO(Scoped):
            class ScopedOptions:
                allow_reuse = False

        so = SO()
        with so:
            pass
        self.assertRaises(SO.LifecycleError, lambda: so.open())

    # Nesting

    def test_nestable(self):
        class SO(Scoped):
            class ScopedOptions:
                max_nesting = 3

        with SO():
            with SO():
                with SO():
                    self.assertRaises(SO.LifecycleError, lambda: SO().open())

    def test_non_nestable(self):
        class SO(Scoped):
            class ScopedOptions:
                max_nesting = 1

        with SO():
            self.assertRaises(SO.LifecycleError, lambda: SO().open())

    # Stack inheritance

    def test_stack_inherited(self):
        class Base(Scoped):
            class ScopedOptions:
                max_nesting = 2

        class Sub(Base):
            class ScopedOptions:
                inherit_stack = True

        with Base() as base:
            with Sub() as sub:
                # Sub instance should shadow the base instance
                self.assertEqual(sub, Base.current)

                # Should not be able to close the base scope from within a nested scope
                self.assertRaises(Scoped.LifecycleError, base.close)

    def test_stack_not_inherited(self):
        class Base(Scoped):
            pass

        class Sub(Base):
            class ScopedOptions:
                inherit_stack = False

        base = Base().open()
        sub = Sub().open()

        # Each class should have its own current instance
        self.assertEqual(base, Base.current)
        self.assertEqual(sub, Sub.current)

        # Should be able to leave the scopes in any order
        base.close()
        sub.close()

    def test_default_instance(self):
        class S(Scoped):
            pass
        S.default = S()

        self.assertEqual(S.default, S.current)

    def test_thread_locality(self):
        class SO(Scoped):
            pass

        cond = threading.Condition()

        def other_thread():
            with cond:
                with SO():
                    cond.notify()
                    cond.wait(1.0)

                cond.notify()
                cond.wait(1.0)

        thread = threading.Thread(target=other_thread)

        with cond:
            # Enter scope in secondary thread
            thread.start()
            cond.wait(1.0)

            # Nothing should be in scope in this thread
            self.assertFalse(SO.has_current)

            # Enter scope in this thread
            with SO() as sc:
                self.assertTrue(sc.is_current)

                # Leave scope in secondary thread
                cond.notify()
                cond.wait(1.0)

                # sc should still be in scope here
                self.assertTrue(sc.is_current)

            cond.notify()

        thread.join()
