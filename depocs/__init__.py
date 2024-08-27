"""
Scoped is a mixin class that creates a thread-local stack for each of its
subclasses. Instances of the subclass can be pushed and popped on this stack,
and the instance at the top of the stack is always available as a property of
the class.

Scoped classes are typically used to make parameters implicitly
available within a (dynamic) scope, without having to pass them around as
function arguments. Scoped helps you do this in a safe and convenient way, and
provides very informative error messages when you do something wrong.
"""

import inspect
import sys
import threading


# Copied from six
def with_metaclass(meta, *bases):
    """Create a base class with a metaclass."""

    # This requires a bit of explanation: the basic idea is to make a dummy
    # metaclass for one level of class instantiation that replaces itself with
    # the actual metaclass.
    class metaclass(type):

        def __new__(cls, name, this_bases, d):
            return meta(name, bases, d)

        @classmethod
        def __prepare__(cls, name, this_bases):
            return meta.__prepare__(name, bases)

    return type.__new__(metaclass, "temporary_class", (), {})


class classproperty(property):
    """
    Marries ``@property`` and ``@classmethod``. Why doesn't python have this?
    Grr..
    """

    def __new__(cls, fget, *args):
        return super(classproperty, cls).__new__(cls, classmethod(fget), *args)

    def __get__(self, obj, type=None):
        return self.fget(type)


class ScopedClass(type):
    def __init__(cls, clsname, bases=None, attrs=None):
        super(ScopedClass, cls).__init__(clsname, bases, attrs)

        if not hasattr(cls, "_Scoped__thread_local"):
            # ScopedBase
            return
        elif "_Scoped__thread_local" in attrs:
            # Scoped
            return
        else:
            # subclass of Scoped
            scoped_bases = tuple(
                base for base in bases if isinstance(base, ScopedClass)
            )
            immediate_subclass = (
                len(scoped_bases) == 0 or scoped_bases[0]._Scoped__thread_local is None
            )

            if "ScopedOptions" in attrs:
                meta = dict(
                    (name, getattr(attrs["ScopedOptions"], name))
                    for name in dir(attrs["ScopedOptions"])
                    if name[:2] != "__"
                )
            else:
                meta = {}

            if "inherit_stack" not in meta:
                meta["inherit_stack"] = not immediate_subclass

            if meta["inherit_stack"] and immediate_subclass:
                raise TypeError("Base class does not have a stack to inherit")

            if not meta["inherit_stack"]:
                cls._Scoped__thread_local = threading.local()

            if "max_nesting" in meta and meta["inherit_stack"]:
                raise TypeError("Can't override max_nesting if inheriting the stack")

            if scoped_bases:
                cls.ScopedOptions = type(
                    "ScopedOptions",
                    tuple(base.ScopedOptions for base in scoped_bases),
                    meta,
                )
                cls.Missing = type(
                    "Missing", tuple(base.Missing for base in scoped_bases), {}
                )
                cls.LifecycleError = type(
                    "LifecycleError",
                    tuple(base.LifecycleError for base in scoped_bases),
                    {},
                )


class Scoped(ScopedClass("ScopedBase", (object,), {})):
    """
    Abstract base class for an object representing a scope that can be entered and left
    by explicitly opening and closing the object. Instances can only be accessed from
    the thread they were opened in. Scopes can optionally be nested, and the inner-most
    open instance of a class (or hiearchy of classes) is always available from the
    'current' class property. Scopes are thread-local and can be used independently on
    multiple concurrent threads.

    Basic usage::

        class Session(Scoped):
            def __init__(self, user):
                self.user = user

        with Session(user=some_guy) as s:
            print s.user

    Or the scope can be opened and closed explicitly, if needed::

        s = Session(user=some_guy).open()
        try:
            print s.user
        finally:
            s.close()

    The inner-most scope can be accessed from the class property 'current', and thus
    scoped objects can be used to pass scoped data around implicitly::

        def deeply_nested_function():
            print Session.current.some_guy

        with Session(user=some_guy):
            deeply_nested_function()

    Various options can be set by defining an inner class named 'ScopedOptions'::

        class Session(Scoped):
            class ScopedOptions:
                max_nesting = 3       # Limit nesting to 3-deep
                allow_reuse = True    # Instances can go in and out of scope more than once

        class AdminSession(Session):
            class ScopedOptions:
                inherit_stack = True  # Use the same stack as the parent class

    """

    class Error(Exception):
        pass

    class Missing(Error):
        """
        A current scope is expected and there isn't one
        """

    class LifecycleError(with_metaclass(ScopedClass, Exception)):
        """
        A scope was opened/closed at the wrong time
        """

    class ScopedOptions(object):
        """
        Subclasses can use an inner class named 'ScopedOptions' to set some
        options. Unless otherwise specified, missing options are inherited from
        the ScopedOptions of the parent class.
        """

        inherit_stack = True
        """
        If True, instances will share the stack of their parent class, and
        scopes must be well nested with respect to each other.  If False, this
        class will have its own stack and will be scoped independent of any
        ancestors. The default is to inherit the stack, unless subclassing
        Scoped directly, in which case a new stack must be created. This
        attribute is NOT inherited by subclasses.
        """

        max_nesting = 16
        """
        Maximum number of scopes that can be nested on this stack.  This cannot
        be overridden if inheriting the parent stack.
        """

        allow_reuse = False
        """
        If True, instances can be re-opened after being closed.
        If False, instances can only be opened and closed once.
        """

    _Scoped__thread_local = None

    _Scoped__is_open = False
    _Scoped__is_used = False
    _Scoped__open_site_frame = None

    def open(self, call_site_level=1):
        """
        Opens a new scoped context, adding it to the stack of scopes. Calls for
        the current context will refer to this one.

        ``call_site_level`` is the number of stack frames to skip when
        determining where the scope was opened from.  The default value of 1
        will record the site of the actual call to this method.
        """
        if self.is_open:
            if self.open_site:
                raise self.LifecycleError(
                    "{0}({1}) is already open\n{2}".format(
                        self.__class__.__name__, id(self), self.format_trace("  ")
                    )
                )

        if not self.ScopedOptions.allow_reuse and self.is_used:
            raise self.LifecycleError(
                "{0}({1}) cannot be reused\n{2}".format(
                    self.__class__.__name__, id(self), self.format_trace("  ")
                )
            )

        if not hasattr(self._Scoped__thread_local, "stack"):
            self._Scoped__thread_local.stack = []

        if len(self._Scoped__thread_local.stack) >= self.ScopedOptions.max_nesting:
            raise self.LifecycleError(
                "Cannot nest {0} more than {1} levels\n{2}".format(
                    self.__class__.__name__,
                    self.ScopedOptions.max_nesting,
                    self.format_trace("  "),
                )
            )

        self._Scoped__thread_local.stack.append(self)
        self._Scoped__is_open = True
        self._Scoped__is_used = True

        try:
            self._Scoped__open_site_frame = sys._getframe(call_site_level)
        except ValueError:
            # No frame found, skip
            pass

        return self

    def close(self):
        """
        Closes the current scoped context, removing it from the stack of
        contexts.
        """
        if not self.is_open:
            if not self.ScopedOptions.allow_reuse and self.is_used:
                raise self.LifecycleError(
                    "This {0} has already been closed\n{1}".format(
                        self.__class__.__name__, self.format_trace("  ")
                    )
                )
            else:
                raise self.LifecycleError(
                    "This {0} is not open\n{1}".format(
                        self.__class__.__name__, self.format_trace("  ")
                    )
                )

        if not self.is_current:
            raise self.LifecycleError(
                "This {0} is not at the top of the stack\n{1}".format(
                    self.__class__.__name__, self.format_trace("  ")
                )
            )

        self._Scoped__thread_local.stack.pop()
        self._Scoped__is_open = False

        return self

    def __enter__(self):
        return self.open(call_site_level=2)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @property
    def is_open(self):
        return self._Scoped__is_open

    @property
    def open_site(self) -> inspect.Traceback:
        return inspect.getframeinfo(self._Scoped__open_site_frame)

    @property
    def is_used(self):
        return self._Scoped__is_used

    @property
    def is_current(self):
        return type(self).has_current and type(self).current == self

    @classproperty
    def stack(cls):
        return cls._Scoped__thread_local.stack

    @classproperty
    def has_default(cls):
        return cls.default is not None

    @classproperty
    def default(cls):
        return None

    @classproperty
    def has_topmost(cls):
        return (
            hasattr(cls._Scoped__thread_local, "stack")
            and len(cls._Scoped__thread_local.stack) > 0
        )

    @classproperty
    def topmost(cls):
        if not cls.has_topmost:
            raise cls.Missing("No {0} on the stack".format(cls.__name__))
        return cls._Scoped__thread_local.stack[-1]

    @classproperty
    def has_current(cls):
        return cls.has_topmost or cls.has_default

    @classproperty
    def current(cls):
        if cls.has_topmost:
            return cls.topmost
        elif cls.has_default:
            return cls.default
        else:
            raise cls.Missing("No {0} is in scope".format(cls.__name__))

    @classproperty
    def current_if_any(cls):
        if cls.has_current:
            return cls.current

    @classmethod
    def clear(cls):
        try:
            del cls._Scoped__thread_local.stack
        except AttributeError:
            pass

    def format_trace_entry(self):
        if self.open_site:
            return "{0}({1}) opened at {2}:{3}\n".format(
                self.__class__.__name__, id(self), self.open_site[0], self.open_site[1]
            )
        else:
            return "{0}({1}) opened somewhere\n".format(
                self.__class__.__name__, id(self)
            )

    @classmethod
    def format_trace(cls, prefix=""):
        if hasattr(cls._Scoped__thread_local, "stack"):
            return "".join(
                [
                    prefix + so.format_trace_entry()
                    for so in cls._Scoped__thread_local.stack
                ]
            )
        else:
            return ""
