import inspect
import threading
from new import classobj

class classproperty(property):
    """
    Marries @property and @classmethod
    Why doesn't python have this? Grr..
    """
    def __new__(cls, fget, *args):
        return super(classproperty, cls).__new__(cls, classmethod(fget), *args)

    def __get__(self, obj, type=None):
        return self.fget(type)


class ScopedClass(type):
    def __init__(cls, clsname, bases=None, attrs=None):
        super(ScopedClass, cls).__init__(clsname, bases, attrs)

        if attrs.has_key('ScopedOptions'):
            meta = dict((name, getattr(attrs['ScopedOptions'], name))
                         for name in dir(attrs['ScopedOptions']) if name[:2] != '__')
        else:
            meta = {}

        if not meta.has_key('inherit_stack'):
            meta['inherit_stack'] = cls._Scoped__thread_local is not None

        if meta['inherit_stack'] and cls._Scoped__thread_local is None:
            raise TypeError("No stack to inherit (trying to inherit it from {0}?)".format(Scoped.__name__))

        if not meta['inherit_stack'] and not cls.__dict__.has_key('_Scoped__abstract_base'):
            cls._Scoped__thread_local = threading.local()

        if meta.has_key('max_nesting') and meta['inherit_stack']:
            raise TypeError("Can't override max_nesting if inheriting the stack")

        cls.ScopedOptions = classobj(
            'ScopedOptions',
            tuple([base.ScopedOptions for base in bases if hasattr(base, 'ScopedOptions')]),
            meta)


class Scoped(object):
    """
    Abstract base class for an object representing a scope that can be entered and left
    by explicitly opening and closing the object. Instances can only be accessed from
    the thread they were opened in. Scopes can optionally be nested, and the inner-most
    open instance of a class (or hiearchy of classes) is always available from the
    'current' class property. Scopes are thread-local and can be used independently on
    multiple concurrent threads.

    Basic usage:

        class Session(Scoped):
            def __init__(self, user):
                self.user = user

        with Session(user=some_guy) as s:
            print s.user

    Or the scope can be opened and closed explicitly, if needed:

        s = Session(user=some_guy).open()
        try:
            print s.user
        finally:
            s.close()

    The inner-most scope can be accessed from the class property 'current', and thus
    scoped objects can be used to pass scoped data around implicitly:

        def deeply_nested_function():
            print Session.current.some_guy

        with Session(user=some_guy):
            deeply_nested_function()

    Various options can be set by defining an inner class named 'ScopedOptions':

        class Session(Scoped):
            class ScopedOptions:
                max_nesting = 3       # Limit nesting to 3-deep
                allow_reuse = True    # Instances can go in and out of scope more than once

        class AdminSession(Session):
            class ScopedOptions:
                inherit_stack = True  # Use the same stack as the parent class

    """
    class Error(Exception): pass

    class Missing(Error):
        """
        A current scope is expected and there isn't one
        """

    class LifecycleError(Error):
        """
        A scope was opened/closed at the wrong time
        """

    __metaclass__ = ScopedClass

    # Subclasses can use an inner class named 'ScopedOptions' to set
    # some options. Unless otherwise specified, missing options
    # are inherited from the ScopedOptions of the parent class.
    class ScopedOptions(object):

        # If True, instances will share the stack of their parent class,
        # and scopes must be well nested with respect to each other.
        # If False, this class will have its own stack and will be scoped
        # independent of any ancestors. The default is to inherit the stack,
        # unless subclassing Scoped directly, in which case a new
        # stack must be created. This attribute is NOT inherited by subclasses.
        inherit_stack = False

        # Maximum number of scopes that can be nested on this stack.
        # This cannot be overridden if inheriting the parent stack.
        max_nesting = 16

        # If True, instances can be re-opened after being closed.
        # If False, instances can only be opened and closed once.
        allow_reuse = False


    __thread_local = None
    __abstract_base = True

    __is_open = False
    __is_used = False
    __open_site = None

    def open(self, call_site_level=1):
        """
        call_site_level is the number of stack frames to skip
        when determining where the scope was opened from.
        The default value of 1 will record the site of the
        actual call to this method.
        """
        if self.is_open:
            if self.open_site:
                raise Scoped.LifecycleError("{0}({1}) is already open\n{2}".format(
                    self.__class__.__name__, id(self), self.format_trace("  ")))

        if not self.ScopedOptions.allow_reuse and self.is_used:
            raise Scoped.LifecycleError("{0}({1}) cannot be reused\n{2}".format(
                self.__class__.__name__, id(self), self.format_trace("  ")))

        if not hasattr(self.__thread_local, 'stack'):
            self.__thread_local.stack = []

        if len(self.__thread_local.stack) >= self.ScopedOptions.max_nesting:
            raise Scoped.LifecycleError("Cannot nest {0} more than {1} levels\n{2}".format(
                self.__class__.__name__, self.ScopedOptions.max_nesting, self.format_trace("  ")))

        self.__thread_local.stack.append(self)
        self.__is_open = True
        self.__is_used = True

        stack = inspect.stack()
        if len(stack) > call_site_level:
            self.__open_site = stack[call_site_level]

        return self

    def close(self):
        if not self.is_open:
            if not self.ScopedOptions.allow_reuse and self.is_used:
                raise Scoped.LifecycleError("This {0} has already been closed\n{1}".format(
                    self.__class__.__name__, self.format_trace("  ")))
            else:
                raise Scoped.LifecycleError("This {0} is not open\n{1}".format(
                    self.__class__.__name__, self.format_trace("  ")))

        if not self.is_current:
            raise Scoped.LifecycleError("This {0} is not at the top of the stack\n{1}".format(
                self.__class__.__name__, self.format_trace("  ")))

        self.__thread_local.stack.pop()
        self.__is_open = False

        return self

    def __enter__(self):
        return self.open(call_site_level=2)

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @property
    def is_open(self):
        return self.__is_open

    @property
    def open_site(self):
        return self.__open_site

    @property
    def is_used(self):
        return self.__is_used

    @property
    def is_current(self):
        return type(self).has_current and type(self).current == self

    @classproperty
    def has_default(cls):
        return cls.default is not None

    @classproperty
    def default(cls):
        return None

    @classproperty
    def has_topmost(cls):
        return hasattr(cls.__thread_local, 'stack') and len(cls.__thread_local.stack) > 0

    @classproperty
    def topmost(cls):
        if not cls.has_topmost:
            raise Scoped.Missing("No {0} on the stack".format(cls.__name__))
        return cls.__thread_local.stack[-1]

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
            raise Scoped.Missing("No {0} is in scope".format(cls.__name__))

    @classproperty
    def current_if_any(cls):
        if cls.has_current:
            return cls.current

    @classmethod
    def clear(cls):
        try:
            del cls.__thread_local.stack
        except AttributeError:
            pass

    def format_trace_entry(self):
        if self.open_site:
            return "{0}({1}) opened at {2}:{3}\n".format(
                self.__class__.__name__,
                id(self),
                self.open_site[1],
                self.open_site[2])
        else:
            return "{0}({1}) opened somewhere\n".format(
                self.__class__.__name__, id(self))

    @classmethod
    def format_trace(cls, prefix=""):
        if hasattr(cls.__thread_local, 'stack'):
            return "".join([prefix + so.format_trace_entry() for so in cls.__thread_local.stack])
        else:
            return ""

