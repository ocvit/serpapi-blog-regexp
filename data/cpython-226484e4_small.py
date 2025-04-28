    def _test_cow_mutation(self, mutation):
        # Common code for all BytesIO copy-on-write mutation tests.
        imm = b' ' * 1024
        old_rc = sys.getrefcount(imm)
        memio = self.ioclass(imm)
        self.assertEqual(sys.getrefcount(imm), old_rc + 1)
        mutation(memio)
        self.assertEqual(sys.getrefcount(imm), old_rc)

    @support.cpython_only
    def test_cow_truncate(self):
        # Ensure truncate causes a copy.
        def mutation(memio):
            memio.truncate(1)
        self._test_cow_mutation(mutation)

    @support.cpython_only
    def test_cow_write(self):
        # Ensure write that would not cause a resize still results in a copy.
        def mutation(memio):
            memio.seek(0)
            memio.write(b'foo')
        self._test_cow_mutation(mutation)

    @support.cpython_only
    def test_cow_setstate(self):
        # __setstate__ should cause buffer to be released.
        memio = self.ioclass(b'foooooo')
        state = memio.__getstate__()
        def mutation(memio):
            memio.__setstate__(state)
        self._test_cow_mutation(mutation)

    @support.cpython_only
    def test_cow_mutable(self):
        # BytesIO should accept only Bytes for copy-on-write sharing, since
        # arbitrary buffer-exporting objects like bytearray() aren't guaranteed
        # to be immutable.
        ba = bytearray(1024)
        old_rc = sys.getrefcount(ba)
        memio = self.ioclass(ba)
        self.assertEqual(sys.getrefcount(ba), old_rc)

class CStringIOTest(PyStringIOTest):
    ioclass = io.StringIO
    UnsupportedOperation = io.UnsupportedOperation

    # XXX: For the Python version of io.StringIO, this is highly
    # dependent on the encoding used for the underlying buffer.
    def test_widechar(self):
        buf = self.buftype("\U0002030a\U00020347")
        memio = self.ioclass(buf)

        self.assertEqual(memio.getvalue(), buf)
        self.assertEqual(memio.write(buf), len(buf))
        self.assertEqual(memio.tell(), len(buf))
        self.assertEqual(memio.getvalue(), buf)
        self.assertEqual(memio.write(buf), len(buf))
        self.assertEqual(memio.tell(), len(buf) * 2)
        self.assertEqual(memio.getvalue(), buf + buf)

    def test_getstate(self):
        memio = self.ioclass()
        state = memio.__getstate__()
        self.assertEqual(len(state), 4)
        self.assertIsInstance(state[0], str)
        self.assertIsInstance(state[1], str)
        self.assertIsInstance(state[2], int)
        if state[3] is not None:
            self.assertIsInstance(state[3], dict)
        memio.close()
        self.assertRaises(ValueError, memio.__getstate__)

    def test_setstate(self):
        # This checks whether __setstate__ does proper input validation.
        memio = self.ioclass()
        memio.__setstate__(("no error", "\n", 0, None))
        memio.__setstate__(("no error", "", 0, {'spam': 3}))
        self.assertRaises(ValueError, memio.__setstate__, ("", "f", 0, None))
        self.assertRaises(ValueError, memio.__setstate__, ("", "", -1, None))
        self.assertRaises(TypeError, memio.__setstate__, (b"", "", 0, None))
        self.assertRaises(TypeError, memio.__setstate__, ("", b"", 0, None))
        self.assertRaises(TypeError, memio.__setstate__, ("", "", 0.0, None))
        self.assertRaises(TypeError, memio.__setstate__, ("", "", 0, 0))
        self.assertRaises(TypeError, memio.__setstate__, ("len-test", 0))
        self.assertRaises(TypeError, memio.__setstate__)
        self.assertRaises(TypeError, memio.__setstate__, 0)
        memio.close()
        self.assertRaises(ValueError, memio.__setstate__, ("closed", "", 0, None))


class CStringIOPickleTest(PyStringIOPickleTest):
    UnsupportedOperation = io.UnsupportedOperation

    class ioclass(io.StringIO):
        def __new__(cls, *args, **kwargs):
            return pickle.loads(pickle.dumps(io.StringIO(*args, **kwargs)))
        def __init__(self, *args, **kwargs):
            pass


if __name__ == '__main__':
    unittest.main()
"""Unit tests for the memoryview

   Some tests are in test_bytes. Many tests that require _testbuffer.ndarray
   are in test_buffer.
"""

import unittest
import test.support
import sys
import gc
import weakref
import array
import io
import copy
import pickle
import struct

from test.support import import_helper


class AbstractMemoryTests:
    source_bytes = b"abcdef"

    @property
    def _source(self):
        return self.source_bytes

    @property
    def _types(self):
        return filter(None, [self.ro_type, self.rw_type])

    def check_getitem_with_type(self, tp):
        b = tp(self._source)
        oldrefcount = sys.getrefcount(b)
        m = self._view(b)
        self.assertEqual(m[0], ord(b"a"))
        self.assertIsInstance(m[0], int)
        self.assertEqual(m[5], ord(b"f"))
        self.assertEqual(m[-1], ord(b"f"))
        self.assertEqual(m[-6], ord(b"a"))
        # Bounds checking
        self.assertRaises(IndexError, lambda: m[6])
        self.assertRaises(IndexError, lambda: m[-7])
        self.assertRaises(IndexError, lambda: m[sys.maxsize])
        self.assertRaises(IndexError, lambda: m[-sys.maxsize])
        # Type checking
        self.assertRaises(TypeError, lambda: m[None])
        self.assertRaises(TypeError, lambda: m[0.0])
        self.assertRaises(TypeError, lambda: m["a"])
        m = None
        self.assertEqual(sys.getrefcount(b), oldrefcount)

    def test_getitem(self):
        for tp in self._types:
            self.check_getitem_with_type(tp)

    def test_iter(self):
        for tp in self._types:
            b = tp(self._source)
            m = self._view(b)
            self.assertEqual(list(m), [m[i] for i in range(len(m))])

    def test_setitem_readonly(self):
        if not self.ro_type:
            self.skipTest("no read-only type to test")
        b = self.ro_type(self._source)
        oldrefcount = sys.getrefcount(b)
        m = self._view(b)
        def setitem(value):
            m[0] = value
        self.assertRaises(TypeError, setitem, b"a")
        self.assertRaises(TypeError, setitem, 65)
        self.assertRaises(TypeError, setitem, memoryview(b"a"))
        m = None
        self.assertEqual(sys.getrefcount(b), oldrefcount)

    def test_setitem_writable(self):
        if not self.rw_type:
            self.skipTest("no writable type to test")
        tp = self.rw_type
        b = self.rw_type(self._source)
        oldrefcount = sys.getrefcount(b)
        m = self._view(b)
        m[0] = ord(b'1')
        self._check_contents(tp, b, b"1bcdef")
        m[0:1] = tp(b"0")
        self._check_contents(tp, b, b"0bcdef")
        m[1:3] = tp(b"12")
        self._check_contents(tp, b, b"012def")
        m[1:1] = tp(b"")
        self._check_contents(tp, b, b"012def")
        m[:] = tp(b"abcdef")
        self._check_contents(tp, b, b"abcdef")

        # Overlapping copies of a view into itself
        m[0:3] = m[2:5]
        self._check_contents(tp, b, b"cdedef")
        m[:] = tp(b"abcdef")
        m[2:5] = m[0:3]
        self._check_contents(tp, b, b"ababcf")

        def setitem(key, value):
            m[key] = tp(value)
        # Bounds checking
        self.assertRaises(IndexError, setitem, 6, b"a")
        self.assertRaises(IndexError, setitem, -7, b"a")
        self.assertRaises(IndexError, setitem, sys.maxsize, b"a")
        self.assertRaises(IndexError, setitem, -sys.maxsize, b"a")
        # Wrong index/slice types
        self.assertRaises(TypeError, setitem, 0.0, b"a")
        self.assertRaises(TypeError, setitem, (0,), b"a")
        self.assertRaises(TypeError, setitem, (slice(0,1,1), 0), b"a")
        self.assertRaises(TypeError, setitem, (0, slice(0,1,1)), b"a")
        self.assertRaises(TypeError, setitem, (0,), b"a")
        self.assertRaises(TypeError, setitem, "a", b"a")
        # Not implemented: multidimensional slices
        slices = (slice(0,1,1), slice(0,1,2))
        self.assertRaises(NotImplementedError, setitem, slices, b"a")
        # Trying to resize the memory object
        exc = ValueError if m.format == 'c' else TypeError
        self.assertRaises(exc, setitem, 0, b"")
        self.assertRaises(exc, setitem, 0, b"ab")
        self.assertRaises(ValueError, setitem, slice(1,1), b"a")
        self.assertRaises(ValueError, setitem, slice(0,2), b"a")

        m = None
        self.assertEqual(sys.getrefcount(b), oldrefcount)

    def test_delitem(self):
        for tp in self._types:
            b = tp(self._source)
            m = self._view(b)
            with self.assertRaises(TypeError):
                del m[1]
            with self.assertRaises(TypeError):
                del m[1:4]

    def test_tobytes(self):
        for tp in self._types:
            m = self._view(tp(self._source))
            b = m.tobytes()
            # This calls self.getitem_type() on each separate byte of b"abcdef"
            expected = b"".join(
                self.getitem_type(bytes([c])) for c in b"abcdef")
            self.assertEqual(b, expected)
            self.assertIsInstance(b, bytes)

    def test_tolist(self):
        for tp in self._types:
            m = self._view(tp(self._source))
            l = m.tolist()
            self.assertEqual(l, list(b"abcdef"))

    def test_compare(self):
        # memoryviews can compare for equality with other objects
        # having the buffer interface.
        for tp in self._types:
            m = self._view(tp(self._source))
            for tp_comp in self._types:
                self.assertTrue(m == tp_comp(b"abcdef"))
                self.assertFalse(m != tp_comp(b"abcdef"))
                self.assertFalse(m == tp_comp(b"abcde"))
                self.assertTrue(m != tp_comp(b"abcde"))
                self.assertFalse(m == tp_comp(b"abcde1"))
                self.assertTrue(m != tp_comp(b"abcde1"))
            self.assertTrue(m == m)
            self.assertTrue(m == m[:])
            self.assertTrue(m[0:6] == m[:])
            self.assertFalse(m[0:5] == m)

            # Comparison with objects which don't support the buffer API
            self.assertFalse(m == "abcdef")
            self.assertTrue(m != "abcdef")
            self.assertFalse("abcdef" == m)
            self.assertTrue("abcdef" != m)

            # Unordered comparisons
            for c in (m, b"abcdef"):
                self.assertRaises(TypeError, lambda: m < c)
                self.assertRaises(TypeError, lambda: c <= m)
                self.assertRaises(TypeError, lambda: m >= c)
                self.assertRaises(TypeError, lambda: c > m)

    def check_attributes_with_type(self, tp):
        m = self._view(tp(self._source))
        self.assertEqual(m.format, self.format)
        self.assertEqual(m.itemsize, self.itemsize)
        self.assertEqual(m.ndim, 1)
        self.assertEqual(m.shape, (6,))
        self.assertEqual(len(m), 6)
        self.assertEqual(m.strides, (self.itemsize,))
        self.assertEqual(m.suboffsets, ())
        return m

    def test_attributes_readonly(self):
        if not self.ro_type:
            self.skipTest("no read-only type to test")
        m = self.check_attributes_with_type(self.ro_type)
        self.assertEqual(m.readonly, True)

    def test_attributes_writable(self):
        if not self.rw_type:
            self.skipTest("no writable type to test")
        m = self.check_attributes_with_type(self.rw_type)
        self.assertEqual(m.readonly, False)

    def test_getbuffer(self):
        # Test PyObject_GetBuffer() on a memoryview object.
        for tp in self._types:
            b = tp(self._source)
            oldrefcount = sys.getrefcount(b)
            m = self._view(b)
            oldviewrefcount = sys.getrefcount(m)
            s = str(m, "utf-8")
            self._check_contents(tp, b, s.encode("utf-8"))
            self.assertEqual(sys.getrefcount(m), oldviewrefcount)
            m = None
            self.assertEqual(sys.getrefcount(b), oldrefcount)

    def test_gc(self):
        for tp in self._types:
            if not isinstance(tp, type):
                # If tp is a factory rather than a plain type, skip
                continue

            class MyView():
                def __init__(self, base):
                    self.m = memoryview(base)
            class MySource(tp):
                pass
            class MyObject:
                pass

            # Create a reference cycle through a memoryview object.
            # This exercises mbuf_clear().
            b = MySource(tp(b'abc'))
            m = self._view(b)
            o = MyObject()
            b.m = m
            b.o = o
            wr = weakref.ref(o)
            b = m = o = None
            # The cycle must be broken
            gc.collect()
            self.assertTrue(wr() is None, wr())

            # This exercises memory_clear().
            m = MyView(tp(b'abc'))
            o = MyObject()
            m.x = m
            m.o = o
            wr = weakref.ref(o)
            m = o = None
            # The cycle must be broken
            gc.collect()
            self.assertTrue(wr() is None, wr())

    def _check_released(self, m, tp):
        check = self.assertRaisesRegex(ValueError, "released")
        with check: bytes(m)
        with check: m.tobytes()
        with check: m.tolist()
        with check: m[0]
        with check: m[0] = b'x'
        with check: len(m)
        with check: m.format
        with check: m.itemsize
        with check: m.ndim
        with check: m.readonly
        with check: m.shape
        with check: m.strides
        with check:
            with m:
                pass
        # str() and repr() still function
        self.assertIn("released memory", str(m))
        self.assertIn("released memory", repr(m))
        self.assertEqual(m, m)
        self.assertNotEqual(m, memoryview(tp(self._source)))
        self.assertNotEqual(m, tp(self._source))

    def test_contextmanager(self):
        for tp in self._types:
            b = tp(self._source)
            m = self._view(b)
            with m as cm:
                self.assertIs(cm, m)
            self._check_released(m, tp)
            m = self._view(b)
            # Can release explicitly inside the context manager
            with m:
                m.release()

    def test_release(self):
        for tp in self._types:
            b = tp(self._source)
            m = self._view(b)
            m.release()
            self._check_released(m, tp)
            # Can be called a second time (it's a no-op)
            m.release()
            self._check_released(m, tp)

    def test_writable_readonly(self):
        # Issue #10451: memoryview incorrectly exposes a readonly
        # buffer as writable causing a segfault if using mmap
        tp = self.ro_type
        if tp is None:
            self.skipTest("no read-only type to test")
        b = tp(self._source)
        m = self._view(b)
        i = io.BytesIO(b'ZZZZ')
        self.assertRaises(TypeError, i.readinto, m)

    def test_getbuf_fail(self):
        self.assertRaises(TypeError, self._view, {})

    def test_hash(self):
        # Memoryviews of readonly (hashable) types are hashable, and they
        # hash as hash(obj.tobytes()).
        tp = self.ro_type
        if tp is None:
            self.skipTest("no read-only type to test")
        b = tp(self._source)
        m = self._view(b)
        self.assertEqual(hash(m), hash(b"abcdef"))
        # Releasing the memoryview keeps the stored hash value (as with weakrefs)
        m.release()
        self.assertEqual(hash(m), hash(b"abcdef"))
        # Hashing a memoryview for the first time after it is released
        # results in an error (as with weakrefs).
        m = self._view(b)
        m.release()
        self.assertRaises(ValueError, hash, m)

    def test_hash_writable(self):
        # Memoryviews of writable types are unhashable
        tp = self.rw_type
        if tp is None:
            self.skipTest("no writable type to test")
        b = tp(self._source)
        m = self._view(b)
        self.assertRaises(ValueError, hash, m)

    def test_weakref(self):
        # Check memoryviews are weakrefable
        for tp in self._types:
            b = tp(self._source)
            m = self._view(b)
            L = []
            def callback(wr, b=b):
                L.append(b)
            wr = weakref.ref(m, callback)
            self.assertIs(wr(), m)
            del m
            test.support.gc_collect()
            self.assertIs(wr(), None)
            self.assertIs(L[0], b)

    def test_reversed(self):
        for tp in self._types:
            b = tp(self._source)
            m = self._view(b)
            aslist = list(reversed(m.tolist()))
            self.assertEqual(list(reversed(m)), aslist)
            self.assertEqual(list(reversed(m)), list(m[::-1]))

    def test_toreadonly(self):
        for tp in self._types:
            b = tp(self._source)
            m = self._view(b)
            mm = m.toreadonly()
            self.assertTrue(mm.readonly)
            self.assertTrue(memoryview(mm).readonly)
            self.assertEqual(mm.tolist(), m.tolist())
            mm.release()
            m.tolist()

    def test_issue22668(self):
        a = array.array('H', [256, 256, 256, 256])
        x = memoryview(a)
        m = x.cast('B')
        b = m.cast('H')
        c = b[0:2]
        d = memoryview(b)

        del b

        self.assertEqual(c[0], 256)
        self.assertEqual(d[0], 256)
        self.assertEqual(c.format, "H")
        self.assertEqual(d.format, "H")

        _ = m.cast('I')
        self.assertEqual(c[0], 256)
        self.assertEqual(d[0], 256)
        self.assertEqual(c.format, "H")
        self.assertEqual(d.format, "H")


# Variations on source objects for the buffer: bytes-like objects, then arrays
# with itemsize > 1.
# NOTE: support for multi-dimensional objects is unimplemented.

class BaseBytesMemoryTests(AbstractMemoryTests):
    ro_type = bytes
    rw_type = bytearray
    getitem_type = bytes
    itemsize = 1
    format = 'B'

class BaseArrayMemoryTests(AbstractMemoryTests):
    ro_type = None
    rw_type = lambda self, b: array.array('i', list(b))
    getitem_type = lambda self, b: array.array('i', list(b)).tobytes()
    itemsize = array.array('i').itemsize
    format = 'i'

    @unittest.skip('XXX test should be adapted for non-byte buffers')
    def test_getbuffer(self):
        pass

    @unittest.skip('XXX NotImplementedError: tolist() only supports byte views')
    def test_tolist(self):
        pass


# Variations on indirection levels: memoryview, slice of memoryview,
# slice of slice of memoryview.
# This is important to test allocation subtleties.

class BaseMemoryviewTests:
    def _view(self, obj):
        return memoryview(obj)

    def _check_contents(self, tp, obj, contents):
        self.assertEqual(obj, tp(contents))

class BaseMemorySliceTests:
    source_bytes = b"XabcdefY"

    def _view(self, obj):
        m = memoryview(obj)
        return m[1:7]

    def _check_contents(self, tp, obj, contents):
        self.assertEqual(obj[1:7], tp(contents))

    def test_refs(self):
        for tp in self._types:
            m = memoryview(tp(self._source))
            oldrefcount = sys.getrefcount(m)
            m[1:2]
            self.assertEqual(sys.getrefcount(m), oldrefcount)

class BaseMemorySliceSliceTests:
    source_bytes = b"XabcdefY"

    def _view(self, obj):
        m = memoryview(obj)
        return m[:7][1:]

    def _check_contents(self, tp, obj, contents):
        self.assertEqual(obj[1:7], tp(contents))


# Concrete test classes

class BytesMemoryviewTest(unittest.TestCase,
    BaseMemoryviewTests, BaseBytesMemoryTests):

    def test_constructor(self):
        for tp in self._types:
            ob = tp(self._source)
            self.assertTrue(memoryview(ob))
            self.assertTrue(memoryview(object=ob))
            self.assertRaises(TypeError, memoryview)
            self.assertRaises(TypeError, memoryview, ob, ob)
            self.assertRaises(TypeError, memoryview, argument=ob)
            self.assertRaises(TypeError, memoryview, ob, argument=True)

class ArrayMemoryviewTest(unittest.TestCase,
    BaseMemoryviewTests, BaseArrayMemoryTests):

    def test_array_assign(self):
        # Issue #4569: segfault when mutating a memoryview with itemsize != 1
        a = array.array('i', range(10))
        m = memoryview(a)
        new_a = array.array('i', range(9, -1, -1))
        m[:] = new_a
        self.assertEqual(a, new_a)


class BytesMemorySliceTest(unittest.TestCase,
    BaseMemorySliceTests, BaseBytesMemoryTests):
    pass

class ArrayMemorySliceTest(unittest.TestCase,
    BaseMemorySliceTests, BaseArrayMemoryTests):
    pass

class BytesMemorySliceSliceTest(unittest.TestCase,
    BaseMemorySliceSliceTests, BaseBytesMemoryTests):
    pass

class ArrayMemorySliceSliceTest(unittest.TestCase,
    BaseMemorySliceSliceTests, BaseArrayMemoryTests):
    pass


class OtherTest(unittest.TestCase):
    def test_ctypes_cast(self):
        # Issue 15944: Allow all source formats when casting to bytes.
        ctypes = import_helper.import_module("ctypes")
        p6 = bytes(ctypes.c_double(0.6))

        d = ctypes.c_double()
        m = memoryview(d).cast("B")
        m[:2] = p6[:2]
        m[2:] = p6[2:]
        self.assertEqual(d.value, 0.6)

        for format in "Bbc":
            with self.subTest(format):
                d = ctypes.c_double()
                m = memoryview(d).cast(format)
                m[:2] = memoryview(p6).cast(format)[:2]
                m[2:] = memoryview(p6).cast(format)[2:]
                self.assertEqual(d.value, 0.6)

    def test_half_float(self):
        half_data = struct.pack('eee', 0.0, -1.5, 1.5)
        float_data = struct.pack('fff', 0.0, -1.5, 1.5)
        half_view = memoryview(half_data).cast('e')
        float_view = memoryview(float_data).cast('f')
        self.assertEqual(half_view.nbytes * 2, float_view.nbytes)
        self.assertListEqual(half_view.tolist(), float_view.tolist())

    def test_memoryview_hex(self):
        # Issue #9951: memoryview.hex() segfaults with non-contiguous buffers.
        x = b'0' * 200000
        m1 = memoryview(x)
        m2 = m1[::-1]
        self.assertEqual(m2.hex(), '30' * 200000)

    def test_copy(self):
        m = memoryview(b'abc')
        with self.assertRaises(TypeError):
            copy.copy(m)

    def test_pickle(self):
        m = memoryview(b'abc')
        for proto in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.assertRaises(TypeError):
                pickle.dumps(m, proto)

    def test_use_released_memory(self):
        # gh-92888: Previously it was possible to use a memoryview even after
        # backing buffer is freed in certain cases. This tests that those
        # cases raise an exception.
        size = 128
        def release():
            m.release()
            nonlocal ba
            ba = bytearray(size)
        class MyIndex:
            def __index__(self):
                release()
                return 4
        class MyFloat:
            def __float__(self):
                release()
                return 4.25
        class MyBool:
            def __bool__(self):
                release()
                return True

        ba = None
        m = memoryview(bytearray(b'\xff'*size))
        with self.assertRaises(ValueError):
            m[MyIndex()]

        ba = None
        m = memoryview(bytearray(b'\xff'*size))
        self.assertEqual(list(m[:MyIndex()]), [255] * 4)

        ba = None
        m = memoryview(bytearray(b'\xff'*size))
        self.assertEqual(list(m[MyIndex():8]), [255] * 4)

        ba = None
        m = memoryview(bytearray(b'\xff'*size)).cast('B', (64, 2))
        with self.assertRaisesRegex(ValueError, "operation forbidden"):
            m[MyIndex(), 0]

        ba = None
        m = memoryview(bytearray(b'\xff'*size)).cast('B', (2, 64))
        with self.assertRaisesRegex(ValueError, "operation forbidden"):
            m[0, MyIndex()]

        ba = None
        m = memoryview(bytearray(b'\xff'*size))
        with self.assertRaisesRegex(ValueError, "operation forbidden"):
            m[MyIndex()] = 42
        self.assertEqual(ba[:8], b'\0'*8)

        ba = None
        m = memoryview(bytearray(b'\xff'*size))
        with self.assertRaisesRegex(ValueError, "operation forbidden"):
            m[:MyIndex()] = b'spam'
        self.assertEqual(ba[:8], b'\0'*8)

        ba = None
        m = memoryview(bytearray(b'\xff'*size))
        with self.assertRaisesRegex(ValueError, "operation forbidden"):
            m[MyIndex():8] = b'spam'
        self.assertEqual(ba[:8], b'\0'*8)

        ba = None
        m = memoryview(bytearray(b'\xff'*size)).cast('B', (64, 2))
        with self.assertRaisesRegex(ValueError, "operation forbidden"):
            m[MyIndex(), 0] = 42
        self.assertEqual(ba[8:16], b'\0'*8)
        ba = None
        m = memoryview(bytearray(b'\xff'*size)).cast('B', (2, 64))
        with self.assertRaisesRegex(ValueError, "operation forbidden"):
            m[0, MyIndex()] = 42
        self.assertEqual(ba[:8], b'\0'*8)

        ba = None
        m = memoryview(bytearray(b'\xff'*size))
        with self.assertRaisesRegex(ValueError, "operation forbidden"):
            m[0] = MyIndex()
        self.assertEqual(ba[:8], b'\0'*8)

        for fmt in 'bhilqnBHILQN':
            with self.subTest(fmt=fmt):
                ba = None
                m = memoryview(bytearray(b'\xff'*size)).cast(fmt)
                with self.assertRaisesRegex(ValueError, "operation forbidden"):
                    m[0] = MyIndex()
                self.assertEqual(ba[:8], b'\0'*8)

        for fmt in 'fd':
            with self.subTest(fmt=fmt):
                ba = None
                m = memoryview(bytearray(b'\xff'*size)).cast(fmt)
                with self.assertRaisesRegex(ValueError, "operation forbidden"):
                    m[0] = MyFloat()
                self.assertEqual(ba[:8], b'\0'*8)

        ba = None
        m = memoryview(bytearray(b'\xff'*size)).cast('?')
        with self.assertRaisesRegex(ValueError, "operation forbidden"):
            m[0] = MyBool()
        self.assertEqual(ba[:8], b'\0'*8)

if __name__ == "__main__":
    unittest.main()
import doctest
import unittest


doctests = """

Basic class construction.

    >>> class C:
    ...     def meth(self): print("Hello")
    ...
    >>> C.__class__ is type
    True
    >>> a = C()
    >>> a.__class__ is C
    True
    >>> a.meth()
    Hello
    >>>

Use *args notation for the bases.

    >>> class A: pass
    >>> class B: pass
    >>> bases = (A, B)
    >>> class C(*bases): pass
    >>> C.__bases__ == bases
    True
    >>>

Use a trivial metaclass.

    >>> class M(type):
    ...     pass
    ...
    >>> class C(metaclass=M):
    ...    def meth(self): print("Hello")
    ...
    >>> C.__class__ is M
    True
    >>> a = C()
    >>> a.__class__ is C
    True
    >>> a.meth()
    Hello
    >>>

Use **kwds notation for the metaclass keyword.

    >>> kwds = {'metaclass': M}
    >>> class C(**kwds): pass
    ...
    >>> C.__class__ is M
    True
    >>> a = C()
    >>> a.__class__ is C
    True
    >>>

Use a metaclass with a __prepare__ static method.

    >>> class M(type):
    ...    @staticmethod
    ...    def __prepare__(*args, **kwds):
    ...        print("Prepare called:", args, kwds)
    ...        return dict()
    ...    def __new__(cls, name, bases, namespace, **kwds):
    ...        print("New called:", kwds)
    ...        return type.__new__(cls, name, bases, namespace)
    ...    def __init__(cls, *args, **kwds):
    ...        pass
    ...
    >>> class C(metaclass=M):
    ...     def meth(self): print("Hello")
    ...
    Prepare called: ('C', ()) {}
    New called: {}
    >>>

Also pass another keyword.

    >>> class C(object, metaclass=M, other="haha"):
    ...     pass
    ...
    Prepare called: ('C', (<class 'object'>,)) {'other': 'haha'}
    New called: {'other': 'haha'}
    >>> C.__class__ is M
    True
    >>> C.__bases__ == (object,)
    True
    >>> a = C()
    >>> a.__class__ is C
    True
    >>>

Check that build_class doesn't mutate the kwds dict.

    >>> kwds = {'metaclass': type}
    >>> class C(**kwds): pass
    ...
    >>> kwds == {'metaclass': type}
    True
    >>>

Use various combinations of explicit keywords and **kwds.

    >>> bases = (object,)
    >>> kwds = {'metaclass': M, 'other': 'haha'}
    >>> class C(*bases, **kwds): pass
    ...
    Prepare called: ('C', (<class 'object'>,)) {'other': 'haha'}
    New called: {'other': 'haha'}
    >>> C.__class__ is M
    True
    >>> C.__bases__ == (object,)
    True
    >>> class B: pass
    >>> kwds = {'other': 'haha'}
    >>> class C(B, metaclass=M, *bases, **kwds): pass
    ...
    Prepare called: ('C', (<class 'test.test_metaclass.B'>, <class 'object'>)) {'other': 'haha'}
    New called: {'other': 'haha'}
    >>> C.__class__ is M
    True
    >>> C.__bases__ == (B, object)
    True
    >>>

Check for duplicate keywords.

    >>> class C(metaclass=type, metaclass=type): pass
    ...
    Traceback (most recent call last):
    [...]
    SyntaxError: keyword argument repeated: metaclass
    >>>

Another way.

    >>> kwds = {'metaclass': type}
    >>> class C(metaclass=type, **kwds): pass
    ...
    Traceback (most recent call last):
    [...]
    TypeError: __build_class__() got multiple values for keyword argument 'metaclass'
    >>>

Use a __prepare__ method that returns an instrumented dict.

    >>> class LoggingDict(dict):
    ...     def __setitem__(self, key, value):
    ...         print("d[%r] = %r" % (key, value))
    ...         dict.__setitem__(self, key, value)
    ...
    >>> class Meta(type):
    ...    @staticmethod
    ...    def __prepare__(name, bases):
    ...        return LoggingDict()
    ...
    >>> class C(metaclass=Meta):
    ...     foo = 2+2
    ...     foo = 42
    ...     bar = 123
    ...
    d['__module__'] = 'test.test_metaclass'
    d['__qualname__'] = 'C'
    d['foo'] = 4
    d['foo'] = 42
    d['bar'] = 123
    >>>

Use a metaclass that doesn't derive from type.

    >>> def meta(name, bases, namespace, **kwds):
    ...     print("meta:", name, bases)
    ...     print("ns:", sorted(namespace.items()))
    ...     print("kw:", sorted(kwds.items()))
    ...     return namespace
    ...
    >>> class C(metaclass=meta):
    ...     a = 42
    ...     b = 24
    ...
    meta: C ()
    ns: [('__module__', 'test.test_metaclass'), ('__qualname__', 'C'), ('a', 42), ('b', 24)]
    kw: []
    >>> type(C) is dict
    True
    >>> print(sorted(C.items()))
    [('__module__', 'test.test_metaclass'), ('__qualname__', 'C'), ('a', 42), ('b', 24)]
    >>>

And again, with a __prepare__ attribute.

    >>> def prepare(name, bases, **kwds):
    ...     print("prepare:", name, bases, sorted(kwds.items()))
    ...     return LoggingDict()
    ...
    >>> meta.__prepare__ = prepare
    >>> class C(metaclass=meta, other="booh"):
    ...    a = 1
    ...    a = 2
    ...    b = 3
    ...
    prepare: C () [('other', 'booh')]
    d['__module__'] = 'test.test_metaclass'
    d['__qualname__'] = 'C'
    d['a'] = 1
    d['a'] = 2
    d['b'] = 3
    meta: C ()
    ns: [('__module__', 'test.test_metaclass'), ('__qualname__', 'C'), ('a', 2), ('b', 3)]
    kw: [('other', 'booh')]
    >>>

The default metaclass must define a __prepare__() method.

    >>> type.__prepare__()
    {}
    >>>

Make sure it works with subclassing.

    >>> class M(type):
    ...     @classmethod
    ...     def __prepare__(cls, *args, **kwds):
    ...         d = super().__prepare__(*args, **kwds)
    ...         d["hello"] = 42
    ...         return d
    ...
    >>> class C(metaclass=M):
    ...     print(hello)
    ...
    42
    >>> print(C.hello)
    42
    >>>

Test failures in looking up the __prepare__ method work.
    >>> class ObscureException(Exception):
    ...     pass
    >>> class FailDescr:
    ...     def __get__(self, instance, owner):
    ...        raise ObscureException
    >>> class Meta(type):
    ...     __prepare__ = FailDescr()
    >>> class X(metaclass=Meta):
    ...     pass
    Traceback (most recent call last):
    [...]
    test.test_metaclass.ObscureException

"""

import sys

# Trace function introduces __locals__ which causes various tests to fail.
if hasattr(sys, 'gettrace') and sys.gettrace():
    __test__ = {}
else:
    __test__ = {'doctests' : doctests}

def load_tests(loader, tests, pattern):
    tests.addTest(doctest.DocTestSuite())
    return tests


if __name__ == "__main__":
    unittest.main()
import io
import mimetypes
import pathlib
import sys
import unittest.mock

from test import support
from test.support import os_helper
from platform import win32_edition

try:
    import _winapi
except ImportError:
    _winapi = None


def setUpModule():
    global knownfiles
    knownfiles = mimetypes.knownfiles

    # Tell it we don't know about external files:
    mimetypes.knownfiles = []
    mimetypes.inited = False
    mimetypes._default_mime_types()


def tearDownModule():
    # Restore knownfiles to its initial state
    mimetypes.knownfiles = knownfiles


class MimeTypesTestCase(unittest.TestCase):
    def setUp(self):
        self.db = mimetypes.MimeTypes()

    def test_case_sensitivity(self):
        eq = self.assertEqual
        eq(self.db.guess_type("foobar.HTML"), self.db.guess_type("foobar.html"))
        eq(self.db.guess_type("foobar.TGZ"), self.db.guess_type("foobar.tgz"))
        eq(self.db.guess_type("foobar.tar.Z"), ("application/x-tar", "compress"))
        eq(self.db.guess_type("foobar.tar.z"), (None, None))

    def test_default_data(self):
        eq = self.assertEqual
        eq(self.db.guess_type("foo.html"), ("text/html", None))
        eq(self.db.guess_type("foo.HTML"), ("text/html", None))
        eq(self.db.guess_type("foo.tgz"), ("application/x-tar", "gzip"))
        eq(self.db.guess_type("foo.tar.gz"), ("application/x-tar", "gzip"))
        eq(self.db.guess_type("foo.tar.Z"), ("application/x-tar", "compress"))
        eq(self.db.guess_type("foo.tar.bz2"), ("application/x-tar", "bzip2"))
        eq(self.db.guess_type("foo.tar.xz"), ("application/x-tar", "xz"))

    def test_data_urls(self):
        eq = self.assertEqual
        guess_type = self.db.guess_type
        eq(guess_type("data:invalidDataWithoutComma"), (None, None))
        eq(guess_type("data:,thisIsTextPlain"), ("text/plain", None))
        eq(guess_type("data:;base64,thisIsTextPlain"), ("text/plain", None))
        eq(guess_type("data:text/x-foo,thisIsTextXFoo"), ("text/x-foo", None))

    def test_file_parsing(self):
        eq = self.assertEqual
        sio = io.StringIO("x-application/x-unittest pyunit\n")
        self.db.readfp(sio)
        eq(self.db.guess_type("foo.pyunit"),
           ("x-application/x-unittest", None))
        eq(self.db.guess_extension("x-application/x-unittest"), ".pyunit")

    def test_read_mime_types(self):
        eq = self.assertEqual

        # Unreadable file returns None
        self.assertIsNone(mimetypes.read_mime_types("non-existent"))

        with os_helper.temp_dir() as directory:
            data = "x-application/x-unittest pyunit\n"
            file = pathlib.Path(directory, "sample.mimetype")
            file.write_text(data, encoding="utf-8")
            mime_dict = mimetypes.read_mime_types(file)
            eq(mime_dict[".pyunit"], "x-application/x-unittest")

        # bpo-41048: read_mime_types should read the rule file with 'utf-8' encoding.
        # Not with locale encoding. _bootlocale has been imported because io.open(...)
        # uses it.
        data = "application/no-mans-land  Fran\u00E7ais"
        filename = "filename"
        fp = io.StringIO(data)
        with unittest.mock.patch.object(mimetypes, 'open',
                                        return_value=fp) as mock_open:
            mime_dict = mimetypes.read_mime_types(filename)
            mock_open.assert_called_with(filename, encoding='utf-8')
        eq(mime_dict[".Français"], "application/no-mans-land")

    def test_non_standard_types(self):
        eq = self.assertEqual
        # First try strict
        eq(self.db.guess_type('foo.xul', strict=True), (None, None))
        eq(self.db.guess_extension('image/jpg', strict=True), None)
        eq(self.db.guess_extension('image/webp', strict=True), None)
        # And then non-strict
        eq(self.db.guess_type('foo.xul', strict=False), ('text/xul', None))
        eq(self.db.guess_type('foo.XUL', strict=False), ('text/xul', None))
        eq(self.db.guess_type('foo.invalid', strict=False), (None, None))
        eq(self.db.guess_extension('image/jpg', strict=False), '.jpg')
        eq(self.db.guess_extension('image/JPG', strict=False), '.jpg')
        eq(self.db.guess_extension('image/webp', strict=False), '.webp')

    def test_filename_with_url_delimiters(self):
        # bpo-38449: URL delimiters cases should be handled also.
        # They would have different mime types if interpreted as URL as
        # compared to when interpreted as filename because of the semicolon.
        eq = self.assertEqual
        gzip_expected = ('application/x-tar', 'gzip')
        eq(self.db.guess_type(";1.tar.gz"), gzip_expected)
        eq(self.db.guess_type("?1.tar.gz"), gzip_expected)
        eq(self.db.guess_type("#1.tar.gz"), gzip_expected)
        eq(self.db.guess_type("#1#.tar.gz"), gzip_expected)
        eq(self.db.guess_type(";1#.tar.gz"), gzip_expected)
        eq(self.db.guess_type(";&1=123;?.tar.gz"), gzip_expected)
        eq(self.db.guess_type("?k1=v1&k2=v2.tar.gz"), gzip_expected)
        eq(self.db.guess_type(r" \"\`;b&b&c |.tar.gz"), gzip_expected)

    def test_guess_all_types(self):
        # First try strict.  Use a set here for testing the results because if
        # test_urllib2 is run before test_mimetypes, global state is modified
        # such that the 'all' set will have more items in it.
        all = self.db.guess_all_extensions('text/plain', strict=True)
        self.assertTrue(set(all) >= {'.bat', '.c', '.h', '.ksh', '.pl', '.txt'})
        self.assertEqual(len(set(all)), len(all))  # no duplicates
        # And now non-strict
        all = self.db.guess_all_extensions('image/jpg', strict=False)
        self.assertEqual(all, ['.jpg'])
        # And now for no hits
        all = self.db.guess_all_extensions('image/jpg', strict=True)
        self.assertEqual(all, [])
        # And now for type existing in both strict and non-strict mappings.
        self.db.add_type('test-type', '.strict-ext')
        self.db.add_type('test-type', '.non-strict-ext', strict=False)
        all = self.db.guess_all_extensions('test-type', strict=False)
        self.assertEqual(all, ['.strict-ext', '.non-strict-ext'])
        all = self.db.guess_all_extensions('test-type')
        self.assertEqual(all, ['.strict-ext'])
        # Test that changing the result list does not affect the global state
        all.append('.no-such-ext')
        all = self.db.guess_all_extensions('test-type')
        self.assertNotIn('.no-such-ext', all)

    def test_encoding(self):
        filename = support.findfile("mime.types")
        mimes = mimetypes.MimeTypes([filename])
        exts = mimes.guess_all_extensions('application/vnd.geocube+xml',
                                          strict=True)
        self.assertEqual(exts, ['.g3', '.g\xb3'])

    def test_init_reinitializes(self):
        # Issue 4936: make sure an init starts clean
        # First, put some poison into the types table
        mimetypes.add_type('foo/bar', '.foobar')
        self.assertEqual(mimetypes.guess_extension('foo/bar'), '.foobar')
        # Reinitialize
        mimetypes.init()
        # Poison should be gone.
        self.assertEqual(mimetypes.guess_extension('foo/bar'), None)

    @unittest.skipIf(sys.platform.startswith("win"), "Non-Windows only")
    def test_guess_known_extensions(self):
        # Issue 37529
        # The test fails on Windows because Windows adds mime types from the Registry
        # and that creates some duplicates.
        from mimetypes import types_map
        for v in types_map.values():
            self.assertIsNotNone(mimetypes.guess_extension(v))

    def test_preferred_extension(self):
        def check_extensions():
            self.assertEqual(mimetypes.guess_extension('application/octet-stream'), '.bin')
            self.assertEqual(mimetypes.guess_extension('application/postscript'), '.ps')
            self.assertEqual(mimetypes.guess_extension('application/vnd.apple.mpegurl'), '.m3u')
            self.assertEqual(mimetypes.guess_extension('application/vnd.ms-excel'), '.xls')
            self.assertEqual(mimetypes.guess_extension('application/vnd.ms-powerpoint'), '.ppt')
            self.assertEqual(mimetypes.guess_extension('application/x-texinfo'), '.texi')
            self.assertEqual(mimetypes.guess_extension('application/x-troff'), '.roff')
            self.assertEqual(mimetypes.guess_extension('application/xml'), '.xsl')
            self.assertEqual(mimetypes.guess_extension('audio/mpeg'), '.mp3')
            self.assertEqual(mimetypes.guess_extension('image/avif'), '.avif')
            self.assertEqual(mimetypes.guess_extension('image/jpeg'), '.jpg')
            self.assertEqual(mimetypes.guess_extension('image/tiff'), '.tiff')
            self.assertEqual(mimetypes.guess_extension('message/rfc822'), '.eml')
            self.assertEqual(mimetypes.guess_extension('text/html'), '.html')
            self.assertEqual(mimetypes.guess_extension('text/plain'), '.txt')
            self.assertEqual(mimetypes.guess_extension('video/mpeg'), '.mpeg')
            self.assertEqual(mimetypes.guess_extension('video/quicktime'), '.mov')

        check_extensions()
        mimetypes.init()
        check_extensions()

    def test_init_stability(self):
        mimetypes.init()

        suffix_map = mimetypes.suffix_map
        encodings_map = mimetypes.encodings_map
        types_map = mimetypes.types_map
        common_types = mimetypes.common_types

        mimetypes.init()
        self.assertIsNot(suffix_map, mimetypes.suffix_map)
        self.assertIsNot(encodings_map, mimetypes.encodings_map)
        self.assertIsNot(types_map, mimetypes.types_map)
        self.assertIsNot(common_types, mimetypes.common_types)
        self.assertEqual(suffix_map, mimetypes.suffix_map)
        self.assertEqual(encodings_map, mimetypes.encodings_map)
        self.assertEqual(types_map, mimetypes.types_map)
        self.assertEqual(common_types, mimetypes.common_types)

    def test_path_like_ob(self):
        filename = "LICENSE.txt"
        filepath = pathlib.Path(filename)
        filepath_with_abs_dir = pathlib.Path('/dir/'+filename)
        filepath_relative = pathlib.Path('../dir/'+filename)
        path_dir = pathlib.Path('./')

        expected = self.db.guess_type(filename)

        self.assertEqual(self.db.guess_type(filepath), expected)
        self.assertEqual(self.db.guess_type(
            filepath_with_abs_dir), expected)
        self.assertEqual(self.db.guess_type(filepath_relative), expected)
        self.assertEqual(self.db.guess_type(path_dir), (None, None))

    def test_keywords_args_api(self):
        self.assertEqual(self.db.guess_type(
            url="foo.html", strict=True), ("text/html", None))
        self.assertEqual(self.db.guess_all_extensions(
            type='image/jpg', strict=True), [])
        self.assertEqual(self.db.guess_extension(
            type='image/jpg', strict=False), '.jpg')


@unittest.skipUnless(sys.platform.startswith("win"), "Windows only")
class Win32MimeTypesTestCase(unittest.TestCase):
    def setUp(self):
        # ensure all entries actually come from the Windows registry
        self.original_types_map = mimetypes.types_map.copy()
        mimetypes.types_map.clear()
        mimetypes.init()
        self.db = mimetypes.MimeTypes()

    def tearDown(self):
        # restore default settings
        mimetypes.types_map.clear()
        mimetypes.types_map.update(self.original_types_map)

    @unittest.skipIf(win32_edition() in ('NanoServer', 'WindowsCoreHeadless', 'IoTEdgeOS'),
                                         "MIME types registry keys unavailable")
    def test_registry_parsing(self):
        # the original, minimum contents of the MIME database in the
        # Windows registry is undocumented AFAIK.
        # Use file types that should *always* exist:
        eq = self.assertEqual
        eq(self.db.guess_type("foo.txt"), ("text/plain", None))
        eq(self.db.guess_type("image.jpg"), ("image/jpeg", None))
        eq(self.db.guess_type("image.png"), ("image/png", None))

    @unittest.skipIf(not hasattr(_winapi, "_mimetypes_read_windows_registry"),
                     "read_windows_registry accelerator unavailable")
    def test_registry_accelerator(self):
        from_accel = {}
        from_reg = {}
        _winapi._mimetypes_read_windows_registry(
            lambda v, k: from_accel.setdefault(k, set()).add(v)
        )
        mimetypes.MimeTypes._read_windows_registry(
            lambda v, k: from_reg.setdefault(k, set()).add(v)
        )
        self.assertEqual(list(from_reg), list(from_accel))
        for k in from_reg:
            self.assertEqual(from_reg[k], from_accel[k])


class MiscTestCase(unittest.TestCase):
    def test__all__(self):
        support.check__all__(self, mimetypes)


class MimetypesCliTestCase(unittest.TestCase):

    def mimetypes_cmd(self, *args, **kwargs):
        support.patch(self, sys, "argv", [sys.executable, *args])
        with support.captured_stdout() as output:
            mimetypes._main()
            return output.getvalue().strip()

    def test_help_option(self):
        support.patch(self, sys, "argv", [sys.executable, "-h"])
        with support.captured_stdout() as output:
            with self.assertRaises(SystemExit) as cm:
                mimetypes._main()

        self.assertIn("Usage: mimetypes.py", output.getvalue())
        self.assertEqual(cm.exception.code, 0)

    def test_invalid_option(self):
        support.patch(self, sys, "argv", [sys.executable, "--invalid"])
        with support.captured_stdout() as output:
            with self.assertRaises(SystemExit) as cm:
                mimetypes._main()

        self.assertIn("Usage: mimetypes.py", output.getvalue())
        self.assertEqual(cm.exception.code, 1)

    def test_guess_extension(self):
        eq = self.assertEqual

        extension = self.mimetypes_cmd("-l", "-e", "image/jpg")
        eq(extension, ".jpg")

        extension = self.mimetypes_cmd("-e", "image/jpg")
        eq(extension, "I don't know anything about type image/jpg")

        extension = self.mimetypes_cmd("-e", "image/jpeg")
        eq(extension, ".jpg")

    def test_guess_type(self):
        eq = self.assertEqual

        type_info = self.mimetypes_cmd("-l", "foo.pic")
        eq(type_info, "type: image/pict encoding: None")

        type_info = self.mimetypes_cmd("foo.pic")
        eq(type_info, "I don't know anything about type foo.pic")

if __name__ == "__main__":
    unittest.main()
# test for xml.dom.minidom

import copy
import pickle
import io
from test import support
import unittest

import pyexpat
import xml.dom.minidom

from xml.dom.minidom import parse, Attr, Node, Document, parseString
from xml.dom.minidom import getDOMImplementation
from xml.parsers.expat import ExpatError


tstfile = support.findfile("test.xml", subdir="xmltestdata")
sample = ("<?xml version='1.0' encoding='us-ascii'?>\n"
          "<!DOCTYPE doc PUBLIC 'http://xml.python.org/public'"
          " 'http://xml.python.org/system' [\n"
          "  <!ELEMENT e EMPTY>\n"
          "  <!ENTITY ent SYSTEM 'http://xml.python.org/entity'>\n"
          "]><doc attr='value'> text\n"
          "<?pi sample?> <!-- comment --> <e/> </doc>")

# The tests of DocumentType importing use these helpers to construct
# the documents to work with, since not all DOM builders actually
# create the DocumentType nodes.
def create_doc_without_doctype(doctype=None):
    return getDOMImplementation().createDocument(None, "doc", doctype)

def create_nonempty_doctype():
    doctype = getDOMImplementation().createDocumentType("doc", None, None)
    doctype.entities._seq = []
    doctype.notations._seq = []
    notation = xml.dom.minidom.Notation("my-notation", None,
                                        "http://xml.python.org/notations/my")
    doctype.notations._seq.append(notation)
    entity = xml.dom.minidom.Entity("my-entity", None,
                                    "http://xml.python.org/entities/my",
                                    "my-notation")
    entity.version = "1.0"
    entity.encoding = "utf-8"
    entity.actualEncoding = "us-ascii"
    doctype.entities._seq.append(entity)
    return doctype

def create_doc_with_doctype():
    doctype = create_nonempty_doctype()
    doc = create_doc_without_doctype(doctype)
    doctype.entities.item(0).ownerDocument = doc
    doctype.notations.item(0).ownerDocument = doc
    return doc

class MinidomTest(unittest.TestCase):
    def confirm(self, test, testname = "Test"):
        self.assertTrue(test, testname)

    def checkWholeText(self, node, s):
        t = node.wholeText
        self.confirm(t == s, "looking for %r, found %r" % (s, t))

    def testDocumentAsyncAttr(self):
        doc = Document()
        self.assertFalse(doc.async_)
        self.assertFalse(Document.async_)

    def testParseFromBinaryFile(self):
        with open(tstfile, 'rb') as file:
            dom = parse(file)
            dom.unlink()
            self.confirm(isinstance(dom, Document))

    def testParseFromTextFile(self):
        with open(tstfile, 'r', encoding='iso-8859-1') as file:
            dom = parse(file)
            dom.unlink()
            self.confirm(isinstance(dom, Document))

    def testAttrModeSetsParamsAsAttrs(self):
        attr = Attr("qName", "namespaceURI", "localName", "prefix")
        self.assertEqual(attr.name, "qName")
        self.assertEqual(attr.namespaceURI, "namespaceURI")
        self.assertEqual(attr.prefix, "prefix")
        self.assertEqual(attr.localName, "localName")

    def testAttrModeSetsNonOptionalAttrs(self):
        attr = Attr("qName", "namespaceURI", None, "prefix")
        self.assertEqual(attr.name, "qName")
        self.assertEqual(attr.namespaceURI, "namespaceURI")
        self.assertEqual(attr.prefix, "prefix")
        self.assertEqual(attr.localName, attr.name)

    def testGetElementsByTagName(self):
        dom = parse(tstfile)
        self.confirm(dom.getElementsByTagName("LI") == \
                dom.documentElement.getElementsByTagName("LI"))
        dom.unlink()

    def testInsertBefore(self):
        dom = parseString("<doc><foo/></doc>")
        root = dom.documentElement
        elem = root.childNodes[0]
        nelem = dom.createElement("element")
        root.insertBefore(nelem, elem)
        self.confirm(len(root.childNodes) == 2
                and root.childNodes.length == 2
                and root.childNodes[0] is nelem
                and root.childNodes.item(0) is nelem
                and root.childNodes[1] is elem
                and root.childNodes.item(1) is elem
                and root.firstChild is nelem
                and root.lastChild is elem
                and root.toxml() == "<doc><element/><foo/></doc>"
                , "testInsertBefore -- node properly placed in tree")
        nelem = dom.createElement("element")
        root.insertBefore(nelem, None)
        self.confirm(len(root.childNodes) == 3
                and root.childNodes.length == 3
                and root.childNodes[1] is elem
                and root.childNodes.item(1) is elem
                and root.childNodes[2] is nelem
                and root.childNodes.item(2) is nelem
                and root.lastChild is nelem
                and nelem.previousSibling is elem
                and root.toxml() == "<doc><element/><foo/><element/></doc>"
                , "testInsertBefore -- node properly placed in tree")
        nelem2 = dom.createElement("bar")
        root.insertBefore(nelem2, nelem)
        self.confirm(len(root.childNodes) == 4
                and root.childNodes.length == 4
                and root.childNodes[2] is nelem2
                and root.childNodes.item(2) is nelem2
                and root.childNodes[3] is nelem
                and root.childNodes.item(3) is nelem
                and nelem2.nextSibling is nelem
                and nelem.previousSibling is nelem2
                and root.toxml() ==
                "<doc><element/><foo/><bar/><element/></doc>"
                , "testInsertBefore -- node properly placed in tree")
        dom.unlink()

    def _create_fragment_test_nodes(self):
        dom = parseString("<doc/>")
        orig = dom.createTextNode("original")
        c1 = dom.createTextNode("foo")
        c2 = dom.createTextNode("bar")
        c3 = dom.createTextNode("bat")
        dom.documentElement.appendChild(orig)
        frag = dom.createDocumentFragment()
        frag.appendChild(c1)
        frag.appendChild(c2)
        frag.appendChild(c3)
        return dom, orig, c1, c2, c3, frag

    def testInsertBeforeFragment(self):
        dom, orig, c1, c2, c3, frag = self._create_fragment_test_nodes()
        dom.documentElement.insertBefore(frag, None)
        self.confirm(tuple(dom.documentElement.childNodes) ==
                     (orig, c1, c2, c3),
                     "insertBefore(<fragment>, None)")
        frag.unlink()
        dom.unlink()

        dom, orig, c1, c2, c3, frag = self._create_fragment_test_nodes()
        dom.documentElement.insertBefore(frag, orig)
        self.confirm(tuple(dom.documentElement.childNodes) ==
                     (c1, c2, c3, orig),
                     "insertBefore(<fragment>, orig)")
        frag.unlink()
        dom.unlink()

    def testAppendChild(self):
        dom = parse(tstfile)
        dom.documentElement.appendChild(dom.createComment("Hello"))
        self.confirm(dom.documentElement.childNodes[-1].nodeName == "#comment")
        self.confirm(dom.documentElement.childNodes[-1].data == "Hello")
        dom.unlink()

    def testAppendChildFragment(self):
        dom, orig, c1, c2, c3, frag = self._create_fragment_test_nodes()
        dom.documentElement.appendChild(frag)
        self.confirm(tuple(dom.documentElement.childNodes) ==
                     (orig, c1, c2, c3),
                     "appendChild(<fragment>)")
        frag.unlink()
        dom.unlink()

    def testReplaceChildFragment(self):
        dom, orig, c1, c2, c3, frag = self._create_fragment_test_nodes()
        dom.documentElement.replaceChild(frag, orig)
        orig.unlink()
        self.confirm(tuple(dom.documentElement.childNodes) == (c1, c2, c3),
                "replaceChild(<fragment>)")
        frag.unlink()
        dom.unlink()

    def testLegalChildren(self):
        dom = Document()
        elem = dom.createElement('element')
        text = dom.createTextNode('text')
        self.assertRaises(xml.dom.HierarchyRequestErr, dom.appendChild, text)

        dom.appendChild(elem)
        self.assertRaises(xml.dom.HierarchyRequestErr, dom.insertBefore, text,
                          elem)
        self.assertRaises(xml.dom.HierarchyRequestErr, dom.replaceChild, text,
                          elem)

        nodemap = elem.attributes
        self.assertRaises(xml.dom.HierarchyRequestErr, nodemap.setNamedItem,
                          text)
        self.assertRaises(xml.dom.HierarchyRequestErr, nodemap.setNamedItemNS,
                          text)

        elem.appendChild(text)
        dom.unlink()

    def testNamedNodeMapSetItem(self):
        dom = Document()
        elem = dom.createElement('element')
        attrs = elem.attributes
        attrs["foo"] = "bar"
        a = attrs.item(0)
        self.confirm(a.ownerDocument is dom,
                "NamedNodeMap.__setitem__() sets ownerDocument")
        self.confirm(a.ownerElement is elem,
                "NamedNodeMap.__setitem__() sets ownerElement")
        self.confirm(a.value == "bar",
                "NamedNodeMap.__setitem__() sets value")
        self.confirm(a.nodeValue == "bar",
                "NamedNodeMap.__setitem__() sets nodeValue")
        elem.unlink()
        dom.unlink()

    def testNonZero(self):
        dom = parse(tstfile)
        self.confirm(dom)# should not be zero
        dom.appendChild(dom.createComment("foo"))
        self.confirm(not dom.childNodes[-1].childNodes)
        dom.unlink()

    def testUnlink(self):
        dom = parse(tstfile)
        self.assertTrue(dom.childNodes)
        dom.unlink()
        self.assertFalse(dom.childNodes)

    def testContext(self):
        with parse(tstfile) as dom:
            self.assertTrue(dom.childNodes)
        self.assertFalse(dom.childNodes)

    def testElement(self):
        dom = Document()
        dom.appendChild(dom.createElement("abc"))
        self.confirm(dom.documentElement)
        dom.unlink()

    def testAAA(self):
        dom = parseString("<abc/>")
        el = dom.documentElement
        el.setAttribute("spam", "jam2")
        self.confirm(el.toxml() == '<abc spam="jam2"/>', "testAAA")
        a = el.getAttributeNode("spam")
        self.confirm(a.ownerDocument is dom,
                "setAttribute() sets ownerDocument")
        self.confirm(a.ownerElement is dom.documentElement,
                "setAttribute() sets ownerElement")
        dom.unlink()

    def testAAB(self):
        dom = parseString("<abc/>")
        el = dom.documentElement
        el.setAttribute("spam", "jam")
        el.setAttribute("spam", "jam2")
        self.confirm(el.toxml() == '<abc spam="jam2"/>', "testAAB")
        dom.unlink()

    def testAddAttr(self):
        dom = Document()
        child = dom.appendChild(dom.createElement("abc"))

        child.setAttribute("def", "ghi")
        self.confirm(child.getAttribute("def") == "ghi")
        self.confirm(child.attributes["def"].value == "ghi")

        child.setAttribute("jkl", "mno")
        self.confirm(child.getAttribute("jkl") == "mno")
        self.confirm(child.attributes["jkl"].value == "mno")

        self.confirm(len(child.attributes) == 2)

        child.setAttribute("def", "newval")
        self.confirm(child.getAttribute("def") == "newval")
        self.confirm(child.attributes["def"].value == "newval")

        self.confirm(len(child.attributes) == 2)
        dom.unlink()

    def testDeleteAttr(self):
        dom = Document()
        child = dom.appendChild(dom.createElement("abc"))

        self.confirm(len(child.attributes) == 0)
        child.setAttribute("def", "ghi")
        self.confirm(len(child.attributes) == 1)
        del child.attributes["def"]
        self.confirm(len(child.attributes) == 0)
        dom.unlink()

    def testRemoveAttr(self):
        dom = Document()
        child = dom.appendChild(dom.createElement("abc"))

        child.setAttribute("def", "ghi")
        self.confirm(len(child.attributes) == 1)
        self.assertRaises(xml.dom.NotFoundErr, child.removeAttribute, "foo")
        child.removeAttribute("def")
        self.confirm(len(child.attributes) == 0)
        dom.unlink()

    def testRemoveAttrNS(self):
        dom = Document()
        child = dom.appendChild(
                dom.createElementNS("http://www.python.org", "python:abc"))
        child.setAttributeNS("http://www.w3.org", "xmlns:python",
                                                "http://www.python.org")
        child.setAttributeNS("http://www.python.org", "python:abcattr", "foo")
        self.assertRaises(xml.dom.NotFoundErr, child.removeAttributeNS,
            "foo", "http://www.python.org")
        self.confirm(len(child.attributes) == 2)
        child.removeAttributeNS("http://www.python.org", "abcattr")
        self.confirm(len(child.attributes) == 1)
        dom.unlink()

    def testRemoveAttributeNode(self):
        dom = Document()
        child = dom.appendChild(dom.createElement("foo"))
        child.setAttribute("spam", "jam")
        self.confirm(len(child.attributes) == 1)
        node = child.getAttributeNode("spam")
        self.assertRaises(xml.dom.NotFoundErr, child.removeAttributeNode,
            None)
        self.assertIs(node, child.removeAttributeNode(node))
        self.confirm(len(child.attributes) == 0
                and child.getAttributeNode("spam") is None)
        dom2 = Document()
        child2 = dom2.appendChild(dom2.createElement("foo"))
        node2 = child2.getAttributeNode("spam")
        self.assertRaises(xml.dom.NotFoundErr, child2.removeAttributeNode,
            node2)
        dom.unlink()

    def testHasAttribute(self):
        dom = Document()
        child = dom.appendChild(dom.createElement("foo"))
        child.setAttribute("spam", "jam")
        self.confirm(child.hasAttribute("spam"))

    def testChangeAttr(self):
        dom = parseString("<abc/>")
        el = dom.documentElement
        el.setAttribute("spam", "jam")
        self.confirm(len(el.attributes) == 1)
        el.setAttribute("spam", "bam")
        # Set this attribute to be an ID and make sure that doesn't change
        # when changing the value:
        el.setIdAttribute("spam")
        self.confirm(len(el.attributes) == 1
                and el.attributes["spam"].value == "bam"
                and el.attributes["spam"].nodeValue == "bam"
                and el.getAttribute("spam") == "bam"
                and el.getAttributeNode("spam").isId)
        el.attributes["spam"] = "ham"
        self.confirm(len(el.attributes) == 1
                and el.attributes["spam"].value == "ham"
                and el.attributes["spam"].nodeValue == "ham"
                and el.getAttribute("spam") == "ham"
                and el.attributes["spam"].isId)
        el.setAttribute("spam2", "bam")
        self.confirm(len(el.attributes) == 2
                and el.attributes["spam"].value == "ham"
                and el.attributes["spam"].nodeValue == "ham"
                and el.getAttribute("spam") == "ham"
                and el.attributes["spam2"].value == "bam"
                and el.attributes["spam2"].nodeValue == "bam"
                and el.getAttribute("spam2") == "bam")
        el.attributes["spam2"] = "bam2"
        self.confirm(len(el.attributes) == 2
                and el.attributes["spam"].value == "ham"
                and el.attributes["spam"].nodeValue == "ham"
                and el.getAttribute("spam") == "ham"
                and el.attributes["spam2"].value == "bam2"
                and el.attributes["spam2"].nodeValue == "bam2"
                and el.getAttribute("spam2") == "bam2")
        dom.unlink()

    def testGetAttrList(self):
        pass

    def testGetAttrValues(self):
        pass

    def testGetAttrLength(self):
        pass

    def testGetAttribute(self):
        dom = Document()
        child = dom.appendChild(
            dom.createElementNS("http://www.python.org", "python:abc"))
        self.assertEqual(child.getAttribute('missing'), '')

    def testGetAttributeNS(self):
        dom = Document()
        child = dom.appendChild(
                dom.createElementNS("http://www.python.org", "python:abc"))
        child.setAttributeNS("http://www.w3.org", "xmlns:python",
                                                "http://www.python.org")
        self.assertEqual(child.getAttributeNS("http://www.w3.org", "python"),
            'http://www.python.org')
        self.assertEqual(child.getAttributeNS("http://www.w3.org", "other"),
            '')
        child2 = child.appendChild(dom.createElement('abc'))
        self.assertEqual(child2.getAttributeNS("http://www.python.org", "missing"),
                         '')

    def testGetAttributeNode(self): pass

    def testGetElementsByTagNameNS(self):
        d="""<foo xmlns:minidom='http://pyxml.sf.net/minidom'>
        <minidom:myelem/>
        </foo>"""
        dom = parseString(d)
        elems = dom.getElementsByTagNameNS("http://pyxml.sf.net/minidom",
                                           "myelem")
        self.confirm(len(elems) == 1
                and elems[0].namespaceURI == "http://pyxml.sf.net/minidom"
                and elems[0].localName == "myelem"
                and elems[0].prefix == "minidom"
                and elems[0].tagName == "minidom:myelem"
                and elems[0].nodeName == "minidom:myelem")
        dom.unlink()

    def get_empty_nodelist_from_elements_by_tagName_ns_helper(self, doc, nsuri,
                                                              lname):
        nodelist = doc.getElementsByTagNameNS(nsuri, lname)
        self.confirm(len(nodelist) == 0)

    def testGetEmptyNodeListFromElementsByTagNameNS(self):
        doc = parseString('<doc/>')
        self.get_empty_nodelist_from_elements_by_tagName_ns_helper(
            doc, 'http://xml.python.org/namespaces/a', 'localname')
        self.get_empty_nodelist_from_elements_by_tagName_ns_helper(
            doc, '*', 'splat')
        self.get_empty_nodelist_from_elements_by_tagName_ns_helper(
            doc, 'http://xml.python.org/namespaces/a', '*')

        doc = parseString('<doc xmlns="http://xml.python.org/splat"><e/></doc>')
        self.get_empty_nodelist_from_elements_by_tagName_ns_helper(
            doc, "http://xml.python.org/splat", "not-there")
        self.get_empty_nodelist_from_elements_by_tagName_ns_helper(
            doc, "*", "not-there")
        self.get_empty_nodelist_from_elements_by_tagName_ns_helper(
            doc, "http://somewhere.else.net/not-there", "e")

    def testElementReprAndStr(self):
        dom = Document()
        el = dom.appendChild(dom.createElement("abc"))
        string1 = repr(el)
        string2 = str(el)
        self.confirm(string1 == string2)
        dom.unlink()

    def testElementReprAndStrUnicode(self):
        dom = Document()
        el = dom.appendChild(dom.createElement("abc"))
        string1 = repr(el)
        string2 = str(el)
        self.confirm(string1 == string2)
        dom.unlink()

    def testElementReprAndStrUnicodeNS(self):
        dom = Document()
        el = dom.appendChild(
            dom.createElementNS("http://www.slashdot.org", "slash:abc"))
        string1 = repr(el)
        string2 = str(el)
        self.confirm(string1 == string2)
        self.confirm("slash:abc" in string1)
        dom.unlink()

    def testAttributeRepr(self):
        dom = Document()
        el = dom.appendChild(dom.createElement("abc"))
        node = el.setAttribute("abc", "def")
        self.confirm(str(node) == repr(node))
        dom.unlink()

    def testTextNodeRepr(self): pass

    def testWriteXML(self):
        str = '<?xml version="1.0" ?><a b="c"/>'
        dom = parseString(str)
        domstr = dom.toxml()
        dom.unlink()
        self.confirm(str == domstr)

    def testAltNewline(self):
        str = '<?xml version="1.0" ?>\n<a b="c"/>\n'
        dom = parseString(str)
        domstr = dom.toprettyxml(newl="\r\n")
        dom.unlink()
        self.confirm(domstr == str.replace("\n", "\r\n"))

    def test_toprettyxml_with_text_nodes(self):
        # see issue #4147, text nodes are not indented
        decl = '<?xml version="1.0" ?>\n'
        self.assertEqual(parseString('<B>A</B>').toprettyxml(),
                         decl + '<B>A</B>\n')
        self.assertEqual(parseString('<C>A<B>A</B></C>').toprettyxml(),
                         decl + '<C>\n\tA\n\t<B>A</B>\n</C>\n')
        self.assertEqual(parseString('<C><B>A</B>A</C>').toprettyxml(),
                         decl + '<C>\n\t<B>A</B>\n\tA\n</C>\n')
        self.assertEqual(parseString('<C><B>A</B><B>A</B></C>').toprettyxml(),
                         decl + '<C>\n\t<B>A</B>\n\t<B>A</B>\n</C>\n')
        self.assertEqual(parseString('<C><B>A</B>A<B>A</B></C>').toprettyxml(),
                         decl + '<C>\n\t<B>A</B>\n\tA\n\t<B>A</B>\n</C>\n')

    def test_toprettyxml_with_adjacent_text_nodes(self):
        # see issue #4147, adjacent text nodes are indented normally
        dom = Document()
        elem = dom.createElement('elem')
        elem.appendChild(dom.createTextNode('TEXT'))
        elem.appendChild(dom.createTextNode('TEXT'))
        dom.appendChild(elem)
        decl = '<?xml version="1.0" ?>\n'
        self.assertEqual(dom.toprettyxml(),
                         decl + '<elem>\n\tTEXT\n\tTEXT\n</elem>\n')

    def test_toprettyxml_preserves_content_of_text_node(self):
        # see issue #4147
        for str in ('<B>A</B>', '<A><B>C</B></A>'):
            dom = parseString(str)
            dom2 = parseString(dom.toprettyxml())
            self.assertEqual(
                dom.getElementsByTagName('B')[0].childNodes[0].toxml(),
                dom2.getElementsByTagName('B')[0].childNodes[0].toxml())

    def testProcessingInstruction(self):
        dom = parseString('<e><?mypi \t\n data \t\n ?></e>')
        pi = dom.documentElement.firstChild
        self.confirm(pi.target == "mypi"
                and pi.data == "data \t\n "
                and pi.nodeName == "mypi"
                and pi.nodeType == Node.PROCESSING_INSTRUCTION_NODE
                and pi.attributes is None
                and not pi.hasChildNodes()
                and len(pi.childNodes) == 0
                and pi.firstChild is None
                and pi.lastChild is None
                and pi.localName is None
                and pi.namespaceURI == xml.dom.EMPTY_NAMESPACE)

    def testProcessingInstructionRepr(self): pass

    def testTextRepr(self): pass

    def testWriteText(self): pass

    def testDocumentElement(self): pass

    def testTooManyDocumentElements(self):
        doc = parseString("<doc/>")
        elem = doc.createElement("extra")
        # Should raise an exception when adding an extra document element.
        self.assertRaises(xml.dom.HierarchyRequestErr, doc.appendChild, elem)
        elem.unlink()
        doc.unlink()

    def testCreateElementNS(self): pass

    def testCreateAttributeNS(self): pass

    def testParse(self): pass

    def testParseString(self): pass

    def testComment(self): pass

    def testAttrListItem(self): pass

    def testAttrListItems(self): pass

    def testAttrListItemNS(self): pass

    def testAttrListKeys(self): pass

    def testAttrListKeysNS(self): pass

    def testRemoveNamedItem(self):
        doc = parseString("<doc a=''/>")
        e = doc.documentElement
        attrs = e.attributes
        a1 = e.getAttributeNode("a")
        a2 = attrs.removeNamedItem("a")
        self.confirm(a1.isSameNode(a2))
        self.assertRaises(xml.dom.NotFoundErr, attrs.removeNamedItem, "a")

    def testRemoveNamedItemNS(self):
        doc = parseString("<doc xmlns:a='http://xml.python.org/' a:b=''/>")
        e = doc.documentElement
        attrs = e.attributes
        a1 = e.getAttributeNodeNS("http://xml.python.org/", "b")
        a2 = attrs.removeNamedItemNS("http://xml.python.org/", "b")
        self.confirm(a1.isSameNode(a2))
        self.assertRaises(xml.dom.NotFoundErr, attrs.removeNamedItemNS,
                          "http://xml.python.org/", "b")

    def testAttrListValues(self): pass

    def testAttrListLength(self): pass

    def testAttrList__getitem__(self): pass

    def testAttrList__setitem__(self): pass

    def testSetAttrValueandNodeValue(self): pass

    def testParseElement(self): pass

    def testParseAttributes(self): pass

    def testParseElementNamespaces(self): pass

    def testParseAttributeNamespaces(self): pass

    def testParseProcessingInstructions(self): pass

    def testChildNodes(self): pass

    def testFirstChild(self): pass

    def testHasChildNodes(self):
        dom = parseString("<doc><foo/></doc>")
        doc = dom.documentElement
        self.assertTrue(doc.hasChildNodes())
        dom2 = parseString("<doc/>")
        doc2 = dom2.documentElement
        self.assertFalse(doc2.hasChildNodes())

    def _testCloneElementCopiesAttributes(self, e1, e2, test):
        attrs1 = e1.attributes
        attrs2 = e2.attributes
        keys1 = list(attrs1.keys())
        keys2 = list(attrs2.keys())
        keys1.sort()
        keys2.sort()
        self.confirm(keys1 == keys2, "clone of element has same attribute keys")
        for i in range(len(keys1)):
            a1 = attrs1.item(i)
            a2 = attrs2.item(i)
            self.confirm(a1 is not a2
                    and a1.value == a2.value
                    and a1.nodeValue == a2.nodeValue
                    and a1.namespaceURI == a2.namespaceURI
                    and a1.localName == a2.localName
                    , "clone of attribute node has proper attribute values")
            self.confirm(a2.ownerElement is e2,
                    "clone of attribute node correctly owned")

    def _setupCloneElement(self, deep):
        dom = parseString("<doc attr='value'><foo/></doc>")
        root = dom.documentElement
        clone = root.cloneNode(deep)
        self._testCloneElementCopiesAttributes(
            root, clone, "testCloneElement" + (deep and "Deep" or "Shallow"))
        # mutilate the original so shared data is detected
        root.tagName = root.nodeName = "MODIFIED"
        root.setAttribute("attr", "NEW VALUE")
        root.setAttribute("added", "VALUE")
        return dom, clone

    def testCloneElementShallow(self):
        dom, clone = self._setupCloneElement(0)
        self.confirm(len(clone.childNodes) == 0
                and clone.childNodes.length == 0
                and clone.parentNode is None
                and clone.toxml() == '<doc attr="value"/>'
                , "testCloneElementShallow")
        dom.unlink()

    def testCloneElementDeep(self):
        dom, clone = self._setupCloneElement(1)
        self.confirm(len(clone.childNodes) == 1
                and clone.childNodes.length == 1
                and clone.parentNode is None
                and clone.toxml() == '<doc attr="value"><foo/></doc>'
                , "testCloneElementDeep")
        dom.unlink()

    def testCloneDocumentShallow(self):
        doc = parseString("<?xml version='1.0'?>\n"
                    "<!-- comment -->"
                    "<!DOCTYPE doc [\n"
                    "<!NOTATION notation SYSTEM 'http://xml.python.org/'>\n"
                    "]>\n"
                    "<doc attr='value'/>")
        doc2 = doc.cloneNode(0)
        self.confirm(doc2 is None,
                "testCloneDocumentShallow:"
                " shallow cloning of documents makes no sense!")

    def testCloneDocumentDeep(self):
        doc = parseString("<?xml version='1.0'?>\n"
                    "<!-- comment -->"
                    "<!DOCTYPE doc [\n"
                    "<!NOTATION notation SYSTEM 'http://xml.python.org/'>\n"
                    "]>\n"
                    "<doc attr='value'/>")
        doc2 = doc.cloneNode(1)
        self.confirm(not (doc.isSameNode(doc2) or doc2.isSameNode(doc)),
                "testCloneDocumentDeep: document objects not distinct")
        self.confirm(len(doc.childNodes) == len(doc2.childNodes),
                "testCloneDocumentDeep: wrong number of Document children")
        self.confirm(doc2.documentElement.nodeType == Node.ELEMENT_NODE,
                "testCloneDocumentDeep: documentElement not an ELEMENT_NODE")
        self.confirm(doc2.documentElement.ownerDocument.isSameNode(doc2),
            "testCloneDocumentDeep: documentElement owner is not new document")
        self.confirm(not doc.documentElement.isSameNode(doc2.documentElement),
                "testCloneDocumentDeep: documentElement should not be shared")
        if doc.doctype is not None:
            # check the doctype iff the original DOM maintained it
            self.confirm(doc2.doctype.nodeType == Node.DOCUMENT_TYPE_NODE,
                    "testCloneDocumentDeep: doctype not a DOCUMENT_TYPE_NODE")
            self.confirm(doc2.doctype.ownerDocument.isSameNode(doc2))
            self.confirm(not doc.doctype.isSameNode(doc2.doctype))

    def testCloneDocumentTypeDeepOk(self):
        doctype = create_nonempty_doctype()
        clone = doctype.cloneNode(1)
        self.confirm(clone is not None
                and clone.nodeName == doctype.nodeName
                and clone.name == doctype.name
                and clone.publicId == doctype.publicId
                and clone.systemId == doctype.systemId
                and len(clone.entities) == len(doctype.entities)
                and clone.entities.item(len(clone.entities)) is None
                and len(clone.notations) == len(doctype.notations)
                and clone.notations.item(len(clone.notations)) is None
                and len(clone.childNodes) == 0)
        for i in range(len(doctype.entities)):
            se = doctype.entities.item(i)
            ce = clone.entities.item(i)
            self.confirm((not se.isSameNode(ce))
                    and (not ce.isSameNode(se))
                    and ce.nodeName == se.nodeName
                    and ce.notationName == se.notationName
                    and ce.publicId == se.publicId
                    and ce.systemId == se.systemId
                    and ce.encoding == se.encoding
                    and ce.actualEncoding == se.actualEncoding
                    and ce.version == se.version)
        for i in range(len(doctype.notations)):
            sn = doctype.notations.item(i)
            cn = clone.notations.item(i)
            self.confirm((not sn.isSameNode(cn))
                    and (not cn.isSameNode(sn))
                    and cn.nodeName == sn.nodeName
                    and cn.publicId == sn.publicId
                    and cn.systemId == sn.systemId)

    def testCloneDocumentTypeDeepNotOk(self):
        doc = create_doc_with_doctype()
        clone = doc.doctype.cloneNode(1)
        self.confirm(clone is None, "testCloneDocumentTypeDeepNotOk")

    def testCloneDocumentTypeShallowOk(self):
        doctype = create_nonempty_doctype()
        clone = doctype.cloneNode(0)
        self.confirm(clone is not None
                and clone.nodeName == doctype.nodeName
                and clone.name == doctype.name
                and clone.publicId == doctype.publicId
                and clone.systemId == doctype.systemId
                and len(clone.entities) == 0
                and clone.entities.item(0) is None
                and len(clone.notations) == 0
                and clone.notations.item(0) is None
                and len(clone.childNodes) == 0)

    def testCloneDocumentTypeShallowNotOk(self):
        doc = create_doc_with_doctype()
        clone = doc.doctype.cloneNode(0)
        self.confirm(clone is None, "testCloneDocumentTypeShallowNotOk")

    def check_import_document(self, deep, testName):
        doc1 = parseString("<doc/>")
        doc2 = parseString("<doc/>")
        self.assertRaises(xml.dom.NotSupportedErr, doc1.importNode, doc2, deep)

    def testImportDocumentShallow(self):
        self.check_import_document(0, "testImportDocumentShallow")

    def testImportDocumentDeep(self):
        self.check_import_document(1, "testImportDocumentDeep")

    def testImportDocumentTypeShallow(self):
        src = create_doc_with_doctype()
        target = create_doc_without_doctype()
        self.assertRaises(xml.dom.NotSupportedErr, target.importNode,
                          src.doctype, 0)

    def testImportDocumentTypeDeep(self):
        src = create_doc_with_doctype()
        target = create_doc_without_doctype()
        self.assertRaises(xml.dom.NotSupportedErr, target.importNode,
                          src.doctype, 1)

    # Testing attribute clones uses a helper, and should always be deep,
    # even if the argument to cloneNode is false.
    def check_clone_attribute(self, deep, testName):
        doc = parseString("<doc attr='value'/>")
        attr = doc.documentElement.getAttributeNode("attr")
        self.assertNotEqual(attr, None)
        clone = attr.cloneNode(deep)
        self.confirm(not clone.isSameNode(attr))
        self.confirm(not attr.isSameNode(clone))
        self.confirm(clone.ownerElement is None,
                testName + ": ownerElement should be None")
        self.confirm(clone.ownerDocument.isSameNode(attr.ownerDocument),
                testName + ": ownerDocument does not match")
        self.confirm(clone.specified,
                testName + ": cloned attribute must have specified == True")

    def testCloneAttributeShallow(self):
        self.check_clone_attribute(0, "testCloneAttributeShallow")

    def testCloneAttributeDeep(self):
        self.check_clone_attribute(1, "testCloneAttributeDeep")

    def check_clone_pi(self, deep, testName):
        doc = parseString("<?target data?><doc/>")
        pi = doc.firstChild
        self.assertEqual(pi.nodeType, Node.PROCESSING_INSTRUCTION_NODE)
        clone = pi.cloneNode(deep)
        self.confirm(clone.target == pi.target
                and clone.data == pi.data)

    def testClonePIShallow(self):
        self.check_clone_pi(0, "testClonePIShallow")

    def testClonePIDeep(self):
        self.check_clone_pi(1, "testClonePIDeep")

    def check_clone_node_entity(self, clone_document):
        # bpo-35052: Test user data handler in cloneNode() on a document with
        # an entity
        document = xml.dom.minidom.parseString("""
            <?xml version="1.0" ?>
            <!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN"
                "http://www.w3.org/TR/html4/strict.dtd"
                [ <!ENTITY smile "☺"> ]
            >
            <doc>Don't let entities make you frown &smile;</doc>
        """.strip())

        class Handler:
            def handle(self, operation, key, data, src, dst):
                self.operation = operation
                self.key = key
                self.data = data
                self.src = src
                self.dst = dst

        handler = Handler()
        doctype = document.doctype
        entity = doctype.entities['smile']
        entity.setUserData("key", "data", handler)

        if clone_document:
            # clone Document
            clone = document.cloneNode(deep=True)

            self.assertEqual(clone.documentElement.firstChild.wholeText,
                             "Don't let entities make you frown ☺")
            operation = xml.dom.UserDataHandler.NODE_IMPORTED
            dst = clone.doctype.entities['smile']
        else:
            # clone DocumentType
            with support.swap_attr(doctype, 'ownerDocument', None):
                clone = doctype.cloneNode(deep=True)

            operation = xml.dom.UserDataHandler.NODE_CLONED
            dst = clone.entities['smile']

        self.assertEqual(handler.operation, operation)
        self.assertEqual(handler.key, "key")
        self.assertEqual(handler.data, "data")
        self.assertIs(handler.src, entity)
        self.assertIs(handler.dst, dst)

    def testCloneNodeEntity(self):
        self.check_clone_node_entity(False)
        self.check_clone_node_entity(True)

    def testNormalize(self):
        doc = parseString("<doc/>")
        root = doc.documentElement
        root.appendChild(doc.createTextNode("first"))
        root.appendChild(doc.createTextNode("second"))
        self.confirm(len(root.childNodes) == 2
                and root.childNodes.length == 2,
                "testNormalize -- preparation")
        doc.normalize()
        self.confirm(len(root.childNodes) == 1
                and root.childNodes.length == 1
                and root.firstChild is root.lastChild
                and root.firstChild.data == "firstsecond"
                , "testNormalize -- result")
        doc.unlink()

        doc = parseString("<doc/>")
        root = doc.documentElement
        root.appendChild(doc.createTextNode(""))
        doc.normalize()
        self.confirm(len(root.childNodes) == 0
                and root.childNodes.length == 0,
                "testNormalize -- single empty node removed")
        doc.unlink()

    def testNormalizeCombineAndNextSibling(self):
        doc = parseString("<doc/>")
        root = doc.documentElement
        root.appendChild(doc.createTextNode("first"))
        root.appendChild(doc.createTextNode("second"))
        root.appendChild(doc.createElement("i"))
        self.confirm(len(root.childNodes) == 3
                and root.childNodes.length == 3,
                "testNormalizeCombineAndNextSibling -- preparation")
        doc.normalize()
        self.confirm(len(root.childNodes) == 2
                and root.childNodes.length == 2
                and root.firstChild.data == "firstsecond"
                and root.firstChild is not root.lastChild
                and root.firstChild.nextSibling is root.lastChild
                and root.firstChild.previousSibling is None
                and root.lastChild.previousSibling is root.firstChild
                and root.lastChild.nextSibling is None
                , "testNormalizeCombinedAndNextSibling -- result")
        doc.unlink()

    def testNormalizeDeleteWithPrevSibling(self):
        doc = parseString("<doc/>")
        root = doc.documentElement
        root.appendChild(doc.createTextNode("first"))
        root.appendChild(doc.createTextNode(""))
        self.confirm(len(root.childNodes) == 2
                and root.childNodes.length == 2,
                "testNormalizeDeleteWithPrevSibling -- preparation")
        doc.normalize()
        self.confirm(len(root.childNodes) == 1
                and root.childNodes.length == 1
                and root.firstChild.data == "first"
                and root.firstChild is root.lastChild
                and root.firstChild.nextSibling is None
                and root.firstChild.previousSibling is None
                , "testNormalizeDeleteWithPrevSibling -- result")
        doc.unlink()

    def testNormalizeDeleteWithNextSibling(self):
        doc = parseString("<doc/>")
        root = doc.documentElement
        root.appendChild(doc.createTextNode(""))
        root.appendChild(doc.createTextNode("second"))
        self.confirm(len(root.childNodes) == 2
                and root.childNodes.length == 2,
                "testNormalizeDeleteWithNextSibling -- preparation")
        doc.normalize()
        self.confirm(len(root.childNodes) == 1
                and root.childNodes.length == 1
                and root.firstChild.data == "second"
                and root.firstChild is root.lastChild
                and root.firstChild.nextSibling is None
                and root.firstChild.previousSibling is None
                , "testNormalizeDeleteWithNextSibling -- result")
        doc.unlink()

    def testNormalizeDeleteWithTwoNonTextSiblings(self):
        doc = parseString("<doc/>")
        root = doc.documentElement
        root.appendChild(doc.createElement("i"))
        root.appendChild(doc.createTextNode(""))
        root.appendChild(doc.createElement("i"))
        self.confirm(len(root.childNodes) == 3
                and root.childNodes.length == 3,
                "testNormalizeDeleteWithTwoSiblings -- preparation")
        doc.normalize()
        self.confirm(len(root.childNodes) == 2
                and root.childNodes.length == 2
                and root.firstChild is not root.lastChild
                and root.firstChild.nextSibling is root.lastChild
                and root.firstChild.previousSibling is None
                and root.lastChild.previousSibling is root.firstChild
                and root.lastChild.nextSibling is None
                , "testNormalizeDeleteWithTwoSiblings -- result")
        doc.unlink()

    def testNormalizeDeleteAndCombine(self):
        doc = parseString("<doc/>")
        root = doc.documentElement
        root.appendChild(doc.createTextNode(""))
        root.appendChild(doc.createTextNode("second"))
        root.appendChild(doc.createTextNode(""))
        root.appendChild(doc.createTextNode("fourth"))
        root.appendChild(doc.createTextNode(""))
        self.confirm(len(root.childNodes) == 5
                and root.childNodes.length == 5,
                "testNormalizeDeleteAndCombine -- preparation")
        doc.normalize()
        self.confirm(len(root.childNodes) == 1
                and root.childNodes.length == 1
                and root.firstChild is root.lastChild
                and root.firstChild.data == "secondfourth"
                and root.firstChild.previousSibling is None
                and root.firstChild.nextSibling is None
                , "testNormalizeDeleteAndCombine -- result")
        doc.unlink()

    def testNormalizeRecursion(self):
        doc = parseString("<doc>"
                            "<o>"
                              "<i/>"
                              "t"
                              #
                              #x
                            "</o>"
                            "<o>"
                              "<o>"
                                "t2"
                                #x2
                              "</o>"
                              "t3"
                              #x3
                            "</o>"
                            #
                          "</doc>")
        root = doc.documentElement
        root.childNodes[0].appendChild(doc.createTextNode(""))
        root.childNodes[0].appendChild(doc.createTextNode("x"))
        root.childNodes[1].childNodes[0].appendChild(doc.createTextNode("x2"))
        root.childNodes[1].appendChild(doc.createTextNode("x3"))
        root.appendChild(doc.createTextNode(""))
        self.confirm(len(root.childNodes) == 3
                and root.childNodes.length == 3
                and len(root.childNodes[0].childNodes) == 4
                and root.childNodes[0].childNodes.length == 4
                and len(root.childNodes[1].childNodes) == 3
                and root.childNodes[1].childNodes.length == 3
                and len(root.childNodes[1].childNodes[0].childNodes) == 2
                and root.childNodes[1].childNodes[0].childNodes.length == 2
                , "testNormalize2 -- preparation")
        doc.normalize()
        self.confirm(len(root.childNodes) == 2
                and root.childNodes.length == 2
                and len(root.childNodes[0].childNodes) == 2
                and root.childNodes[0].childNodes.length == 2
                and len(root.childNodes[1].childNodes) == 2
                and root.childNodes[1].childNodes.length == 2
                and len(root.childNodes[1].childNodes[0].childNodes) == 1
                and root.childNodes[1].childNodes[0].childNodes.length == 1
                , "testNormalize2 -- childNodes lengths")
        self.confirm(root.childNodes[0].childNodes[1].data == "tx"
                and root.childNodes[1].childNodes[0].childNodes[0].data == "t2x2"
                and root.childNodes[1].childNodes[1].data == "t3x3"
                , "testNormalize2 -- joined text fields")
        self.confirm(root.childNodes[0].childNodes[1].nextSibling is None
                and root.childNodes[0].childNodes[1].previousSibling
                        is root.childNodes[0].childNodes[0]
                and root.childNodes[0].childNodes[0].previousSibling is None
                and root.childNodes[0].childNodes[0].nextSibling
                        is root.childNodes[0].childNodes[1]
                and root.childNodes[1].childNodes[1].nextSibling is None
                and root.childNodes[1].childNodes[1].previousSibling
                        is root.childNodes[1].childNodes[0]
                and root.childNodes[1].childNodes[0].previousSibling is None
                and root.childNodes[1].childNodes[0].nextSibling
                        is root.childNodes[1].childNodes[1]
                , "testNormalize2 -- sibling pointers")
        doc.unlink()


    def testBug0777884(self):
        doc = parseString("<o>text</o>")
        text = doc.documentElement.childNodes[0]
        self.assertEqual(text.nodeType, Node.TEXT_NODE)
        # Should run quietly, doing nothing.
        text.normalize()
        doc.unlink()

    def testBug1433694(self):
        doc = parseString("<o><i/>t</o>")
        node = doc.documentElement
        node.childNodes[1].nodeValue = ""
        node.normalize()
        self.confirm(node.childNodes[-1].nextSibling is None,
                     "Final child's .nextSibling should be None")

    def testSiblings(self):
        doc = parseString("<doc><?pi?>text?<elm/></doc>")
        root = doc.documentElement
        (pi, text, elm) = root.childNodes

        self.confirm(pi.nextSibling is text and
                pi.previousSibling is None and
                text.nextSibling is elm and
                text.previousSibling is pi and
                elm.nextSibling is None and
                elm.previousSibling is text, "testSiblings")

        doc.unlink()

    def testParents(self):
        doc = parseString(
            "<doc><elm1><elm2/><elm2><elm3/></elm2></elm1></doc>")
        root = doc.documentElement
        elm1 = root.childNodes[0]
        (elm2a, elm2b) = elm1.childNodes
        elm3 = elm2b.childNodes[0]

        self.confirm(root.parentNode is doc and
                elm1.parentNode is root and
                elm2a.parentNode is elm1 and
                elm2b.parentNode is elm1 and
                elm3.parentNode is elm2b, "testParents")
        doc.unlink()

    def testNodeListItem(self):
        doc = parseString("<doc><e/><e/></doc>")
        children = doc.childNodes
        docelem = children[0]
        self.confirm(children[0] is children.item(0)
                and children.item(1) is None
                and docelem.childNodes.item(0) is docelem.childNodes[0]
                and docelem.childNodes.item(1) is docelem.childNodes[1]
                and docelem.childNodes.item(0).childNodes.item(0) is None,
                "test NodeList.item()")
        doc.unlink()

    def testEncodings(self):
        doc = parseString('<foo>&#x20ac;</foo>')
        self.assertEqual(doc.toxml(),
                         '<?xml version="1.0" ?><foo>\u20ac</foo>')
        self.assertEqual(doc.toxml('utf-8'),
            b'<?xml version="1.0" encoding="utf-8"?><foo>\xe2\x82\xac</foo>')
        self.assertEqual(doc.toxml('iso-8859-15'),
            b'<?xml version="1.0" encoding="iso-8859-15"?><foo>\xa4</foo>')
        self.assertEqual(doc.toxml('us-ascii'),
            b'<?xml version="1.0" encoding="us-ascii"?><foo>&#8364;</foo>')
        self.assertEqual(doc.toxml('utf-16'),
            '<?xml version="1.0" encoding="utf-16"?>'
            '<foo>\u20ac</foo>'.encode('utf-16'))

        # Verify that character decoding errors raise exceptions instead
        # of crashing
        with self.assertRaises((UnicodeDecodeError, ExpatError)):
            parseString(
                b'<fran\xe7ais>Comment \xe7a va ? Tr\xe8s bien ?</fran\xe7ais>'
            )

        doc.unlink()

    def testStandalone(self):
        doc = parseString('<foo>&#x20ac;</foo>')
        self.assertEqual(doc.toxml(),
                         '<?xml version="1.0" ?><foo>\u20ac</foo>')
        self.assertEqual(doc.toxml(standalone=None),
                         '<?xml version="1.0" ?><foo>\u20ac</foo>')
        self.assertEqual(doc.toxml(standalone=True),
            '<?xml version="1.0" standalone="yes"?><foo>\u20ac</foo>')
        self.assertEqual(doc.toxml(standalone=False),
            '<?xml version="1.0" standalone="no"?><foo>\u20ac</foo>')
        self.assertEqual(doc.toxml('utf-8', True),
            b'<?xml version="1.0" encoding="utf-8" standalone="yes"?>'
            b'<foo>\xe2\x82\xac</foo>')

        doc.unlink()

    class UserDataHandler:
        called = 0
        def handle(self, operation, key, data, src, dst):
            dst.setUserData(key, data + 1, self)
            src.setUserData(key, None, None)
            self.called = 1

    def testUserData(self):
        dom = Document()
        n = dom.createElement('e')
        self.confirm(n.getUserData("foo") is None)
        n.setUserData("foo", None, None)
        self.confirm(n.getUserData("foo") is None)
        n.setUserData("foo", 12, 12)
        n.setUserData("bar", 13, 13)
        self.confirm(n.getUserData("foo") == 12)
        self.confirm(n.getUserData("bar") == 13)
        n.setUserData("foo", None, None)
        self.confirm(n.getUserData("foo") is None)
        self.confirm(n.getUserData("bar") == 13)

        handler = self.UserDataHandler()
        n.setUserData("bar", 12, handler)
        c = n.cloneNode(1)
        self.confirm(handler.called
                and n.getUserData("bar") is None
                and c.getUserData("bar") == 13)
        n.unlink()
        c.unlink()
        dom.unlink()

    def checkRenameNodeSharedConstraints(self, doc, node):
        # Make sure illegal NS usage is detected:
        self.assertRaises(xml.dom.NamespaceErr, doc.renameNode, node,
                          "http://xml.python.org/ns", "xmlns:foo")
        doc2 = parseString("<doc/>")
        self.assertRaises(xml.dom.WrongDocumentErr, doc2.renameNode, node,
                          xml.dom.EMPTY_NAMESPACE, "foo")

    def testRenameAttribute(self):
        doc = parseString("<doc a='v'/>")
        elem = doc.documentElement
        attrmap = elem.attributes
        attr = elem.attributes['a']

        # Simple renaming
        attr = doc.renameNode(attr, xml.dom.EMPTY_NAMESPACE, "b")
        self.confirm(attr.name == "b"
                and attr.nodeName == "b"
                and attr.localName is None
                and attr.namespaceURI == xml.dom.EMPTY_NAMESPACE
                and attr.prefix is None
                and attr.value == "v"
                and elem.getAttributeNode("a") is None
                and elem.getAttributeNode("b").isSameNode(attr)
                and attrmap["b"].isSameNode(attr)
                and attr.ownerDocument.isSameNode(doc)
                and attr.ownerElement.isSameNode(elem))

        # Rename to have a namespace, no prefix
        attr = doc.renameNode(attr, "http://xml.python.org/ns", "c")
        self.confirm(attr.name == "c"
                and attr.nodeName == "c"
                and attr.localName == "c"
                and attr.namespaceURI == "http://xml.python.org/ns"
                and attr.prefix is None
                and attr.value == "v"
                and elem.getAttributeNode("a") is None
                and elem.getAttributeNode("b") is None
                and elem.getAttributeNode("c").isSameNode(attr)
                and elem.getAttributeNodeNS(
                    "http://xml.python.org/ns", "c").isSameNode(attr)
                and attrmap["c"].isSameNode(attr)
                and attrmap[("http://xml.python.org/ns", "c")].isSameNode(attr))

        # Rename to have a namespace, with prefix
        attr = doc.renameNode(attr, "http://xml.python.org/ns2", "p:d")
        self.confirm(attr.name == "p:d"
                and attr.nodeName == "p:d"
                and attr.localName == "d"
                and attr.namespaceURI == "http://xml.python.org/ns2"
                and attr.prefix == "p"
                and attr.value == "v"
                and elem.getAttributeNode("a") is None
                and elem.getAttributeNode("b") is None
                and elem.getAttributeNode("c") is None
                and elem.getAttributeNodeNS(
                    "http://xml.python.org/ns", "c") is None
                and elem.getAttributeNode("p:d").isSameNode(attr)
                and elem.getAttributeNodeNS(
                    "http://xml.python.org/ns2", "d").isSameNode(attr)
                and attrmap["p:d"].isSameNode(attr)
                and attrmap[("http://xml.python.org/ns2", "d")].isSameNode(attr))

        # Rename back to a simple non-NS node
        attr = doc.renameNode(attr, xml.dom.EMPTY_NAMESPACE, "e")
        self.confirm(attr.name == "e"
                and attr.nodeName == "e"
                and attr.localName is None
                and attr.namespaceURI == xml.dom.EMPTY_NAMESPACE
                and attr.prefix is None
                and attr.value == "v"
                and elem.getAttributeNode("a") is None
                and elem.getAttributeNode("b") is None
                and elem.getAttributeNode("c") is None
                and elem.getAttributeNode("p:d") is None
                and elem.getAttributeNodeNS(
                    "http://xml.python.org/ns", "c") is None
                and elem.getAttributeNode("e").isSameNode(attr)
                and attrmap["e"].isSameNode(attr))

        self.assertRaises(xml.dom.NamespaceErr, doc.renameNode, attr,
                          "http://xml.python.org/ns", "xmlns")
        self.checkRenameNodeSharedConstraints(doc, attr)
        doc.unlink()

    def testRenameElement(self):
        doc = parseString("<doc/>")
        elem = doc.documentElement

        # Simple renaming
        elem = doc.renameNode(elem, xml.dom.EMPTY_NAMESPACE, "a")
        self.confirm(elem.tagName == "a"
                and elem.nodeName == "a"
                and elem.localName is None
                and elem.namespaceURI == xml.dom.EMPTY_NAMESPACE
                and elem.prefix is None
                and elem.ownerDocument.isSameNode(doc))

        # Rename to have a namespace, no prefix
        elem = doc.renameNode(elem, "http://xml.python.org/ns", "b")
        self.confirm(elem.tagName == "b"
                and elem.nodeName == "b"
                and elem.localName == "b"
                and elem.namespaceURI == "http://xml.python.org/ns"
                and elem.prefix is None
                and elem.ownerDocument.isSameNode(doc))

        # Rename to have a namespace, with prefix
        elem = doc.renameNode(elem, "http://xml.python.org/ns2", "p:c")
        self.confirm(elem.tagName == "p:c"
                and elem.nodeName == "p:c"
                and elem.localName == "c"
                and elem.namespaceURI == "http://xml.python.org/ns2"
                and elem.prefix == "p"
                and elem.ownerDocument.isSameNode(doc))

        # Rename back to a simple non-NS node
        elem = doc.renameNode(elem, xml.dom.EMPTY_NAMESPACE, "d")
        self.confirm(elem.tagName == "d"
                and elem.nodeName == "d"
                and elem.localName is None
                and elem.namespaceURI == xml.dom.EMPTY_NAMESPACE
                and elem.prefix is None
                and elem.ownerDocument.isSameNode(doc))

        self.checkRenameNodeSharedConstraints(doc, elem)
        doc.unlink()

    def testRenameOther(self):
        # We have to create a comment node explicitly since not all DOM
        # builders used with minidom add comments to the DOM.
        doc = xml.dom.minidom.getDOMImplementation().createDocument(
            xml.dom.EMPTY_NAMESPACE, "e", None)
        node = doc.createComment("comment")
        self.assertRaises(xml.dom.NotSupportedErr, doc.renameNode, node,
                          xml.dom.EMPTY_NAMESPACE, "foo")
        doc.unlink()

    def testWholeText(self):
        doc = parseString("<doc>a</doc>")
        elem = doc.documentElement
        text = elem.childNodes[0]
        self.assertEqual(text.nodeType, Node.TEXT_NODE)

        self.checkWholeText(text, "a")
        elem.appendChild(doc.createTextNode("b"))
        self.checkWholeText(text, "ab")
        elem.insertBefore(doc.createCDATASection("c"), text)
        self.checkWholeText(text, "cab")

        # make sure we don't cross other nodes
        splitter = doc.createComment("comment")
        elem.appendChild(splitter)
        text2 = doc.createTextNode("d")
        elem.appendChild(text2)
        self.checkWholeText(text, "cab")
        self.checkWholeText(text2, "d")

        x = doc.createElement("x")
        elem.replaceChild(x, splitter)
        splitter = x
        self.checkWholeText(text, "cab")
        self.checkWholeText(text2, "d")

        x = doc.createProcessingInstruction("y", "z")
        elem.replaceChild(x, splitter)
        splitter = x
        self.checkWholeText(text, "cab")
        self.checkWholeText(text2, "d")

        elem.removeChild(splitter)
        self.checkWholeText(text, "cabd")
        self.checkWholeText(text2, "cabd")

    def testPatch1094164(self):
        doc = parseString("<doc><e/></doc>")
        elem = doc.documentElement
        e = elem.firstChild
        self.confirm(e.parentNode is elem, "Before replaceChild()")
        # Check that replacing a child with itself leaves the tree unchanged
        elem.replaceChild(e, e)
        self.confirm(e.parentNode is elem, "After replaceChild()")

    def testReplaceWholeText(self):
        def setup():
            doc = parseString("<doc>a<e/>d</doc>")
            elem = doc.documentElement
            text1 = elem.firstChild
            text2 = elem.lastChild
            splitter = text1.nextSibling
            elem.insertBefore(doc.createTextNode("b"), splitter)
            elem.insertBefore(doc.createCDATASection("c"), text1)
            return doc, elem, text1, splitter, text2

        doc, elem, text1, splitter, text2 = setup()
        text = text1.replaceWholeText("new content")
        self.checkWholeText(text, "new content")
        self.checkWholeText(text2, "d")
        self.confirm(len(elem.childNodes) == 3)

        doc, elem, text1, splitter, text2 = setup()
        text = text2.replaceWholeText("new content")
        self.checkWholeText(text, "new content")
        self.checkWholeText(text1, "cab")
        self.confirm(len(elem.childNodes) == 5)

        doc, elem, text1, splitter, text2 = setup()
        text = text1.replaceWholeText("")
        self.checkWholeText(text2, "d")
        self.confirm(text is None
                and len(elem.childNodes) == 2)

    def testSchemaType(self):
        doc = parseString(
            "<!DOCTYPE doc [\n"
            "  <!ENTITY e1 SYSTEM 'http://xml.python.org/e1'>\n"
            "  <!ENTITY e2 SYSTEM 'http://xml.python.org/e2'>\n"
            "  <!ATTLIST doc id   ID       #IMPLIED \n"
            "                ref  IDREF    #IMPLIED \n"
            "                refs IDREFS   #IMPLIED \n"
            "                enum (a|b)    #IMPLIED \n"
            "                ent  ENTITY   #IMPLIED \n"
            "                ents ENTITIES #IMPLIED \n"
            "                nm   NMTOKEN  #IMPLIED \n"
            "                nms  NMTOKENS #IMPLIED \n"
            "                text CDATA    #IMPLIED \n"
            "    >\n"
            "]><doc id='name' notid='name' text='splat!' enum='b'"
            "       ref='name' refs='name name' ent='e1' ents='e1 e2'"
            "       nm='123' nms='123 abc' />")
        elem = doc.documentElement
        # We don't want to rely on any specific loader at this point, so
        # just make sure we can get to all the names, and that the
        # DTD-based namespace is right.  The names can vary by loader
        # since each supports a different level of DTD information.
        t = elem.schemaType
        self.confirm(t.name is None
                and t.namespace == xml.dom.EMPTY_NAMESPACE)
        names = "id notid text enum ref refs ent ents nm nms".split()
        for name in names:
            a = elem.getAttributeNode(name)
            t = a.schemaType
            self.confirm(hasattr(t, "name")
                    and t.namespace == xml.dom.EMPTY_NAMESPACE)

    def testSetIdAttribute(self):
        doc = parseString("<doc a1='v' a2='w'/>")
        e = doc.documentElement
        a1 = e.getAttributeNode("a1")
        a2 = e.getAttributeNode("a2")
        self.confirm(doc.getElementById("v") is None
                and not a1.isId
                and not a2.isId)
        e.setIdAttribute("a1")
        self.confirm(e.isSameNode(doc.getElementById("v"))
                and a1.isId
                and not a2.isId)
        e.setIdAttribute("a2")
        self.confirm(e.isSameNode(doc.getElementById("v"))
                and e.isSameNode(doc.getElementById("w"))
                and a1.isId
                and a2.isId)
        # replace the a1 node; the new node should *not* be an ID
        a3 = doc.createAttribute("a1")
        a3.value = "v"
        e.setAttributeNode(a3)
        self.confirm(doc.getElementById("v") is None
                and e.isSameNode(doc.getElementById("w"))
                and not a1.isId
                and a2.isId
                and not a3.isId)
        # renaming an attribute should not affect its ID-ness:
        doc.renameNode(a2, xml.dom.EMPTY_NAMESPACE, "an")
        self.confirm(e.isSameNode(doc.getElementById("w"))
                and a2.isId)

    def testSetIdAttributeNS(self):
        NS1 = "http://xml.python.org/ns1"
        NS2 = "http://xml.python.org/ns2"
        doc = parseString("<doc"
                          " xmlns:ns1='" + NS1 + "'"
                          " xmlns:ns2='" + NS2 + "'"
                          " ns1:a1='v' ns2:a2='w'/>")
        e = doc.documentElement
        a1 = e.getAttributeNodeNS(NS1, "a1")
        a2 = e.getAttributeNodeNS(NS2, "a2")
        self.confirm(doc.getElementById("v") is None
                and not a1.isId
                and not a2.isId)
        e.setIdAttributeNS(NS1, "a1")
        self.confirm(e.isSameNode(doc.getElementById("v"))
                and a1.isId
                and not a2.isId)
        e.setIdAttributeNS(NS2, "a2")
        self.confirm(e.isSameNode(doc.getElementById("v"))
                and e.isSameNode(doc.getElementById("w"))
                and a1.isId
                and a2.isId)
        # replace the a1 node; the new node should *not* be an ID
        a3 = doc.createAttributeNS(NS1, "a1")
        a3.value = "v"
        e.setAttributeNode(a3)
        self.confirm(e.isSameNode(doc.getElementById("w")))
        self.confirm(not a1.isId)
        self.confirm(a2.isId)
        self.confirm(not a3.isId)
        self.confirm(doc.getElementById("v") is None)
        # renaming an attribute should not affect its ID-ness:
        doc.renameNode(a2, xml.dom.EMPTY_NAMESPACE, "an")
        self.confirm(e.isSameNode(doc.getElementById("w"))
                and a2.isId)

    def testSetIdAttributeNode(self):
        NS1 = "http://xml.python.org/ns1"
        NS2 = "http://xml.python.org/ns2"
        doc = parseString("<doc"
                          " xmlns:ns1='" + NS1 + "'"
                          " xmlns:ns2='" + NS2 + "'"
                          " ns1:a1='v' ns2:a2='w'/>")
        e = doc.documentElement
        a1 = e.getAttributeNodeNS(NS1, "a1")
        a2 = e.getAttributeNodeNS(NS2, "a2")
        self.confirm(doc.getElementById("v") is None
                and not a1.isId
                and not a2.isId)
        e.setIdAttributeNode(a1)
        self.confirm(e.isSameNode(doc.getElementById("v"))
                and a1.isId
                and not a2.isId)
        e.setIdAttributeNode(a2)
        self.confirm(e.isSameNode(doc.getElementById("v"))
                and e.isSameNode(doc.getElementById("w"))
                and a1.isId
                and a2.isId)
        # replace the a1 node; the new node should *not* be an ID
        a3 = doc.createAttributeNS(NS1, "a1")
        a3.value = "v"
        e.setAttributeNode(a3)
        self.confirm(e.isSameNode(doc.getElementById("w")))
        self.confirm(not a1.isId)
        self.confirm(a2.isId)
        self.confirm(not a3.isId)
        self.confirm(doc.getElementById("v") is None)
        # renaming an attribute should not affect its ID-ness:
        doc.renameNode(a2, xml.dom.EMPTY_NAMESPACE, "an")
        self.confirm(e.isSameNode(doc.getElementById("w"))
                and a2.isId)

    def assert_recursive_equal(self, doc, doc2):
        stack = [(doc, doc2)]
        while stack:
            n1, n2 = stack.pop()
            self.assertEqual(n1.nodeType, n2.nodeType)
            self.assertEqual(len(n1.childNodes), len(n2.childNodes))
            self.assertEqual(n1.nodeName, n2.nodeName)
            self.assertFalse(n1.isSameNode(n2))
            self.assertFalse(n2.isSameNode(n1))
            if n1.nodeType == Node.DOCUMENT_TYPE_NODE:
                len(n1.entities)
                len(n2.entities)
                len(n1.notations)
                len(n2.notations)
                self.assertEqual(len(n1.entities), len(n2.entities))
                self.assertEqual(len(n1.notations), len(n2.notations))
                for i in range(len(n1.notations)):
                    # XXX this loop body doesn't seem to be executed?
                    no1 = n1.notations.item(i)
                    no2 = n1.notations.item(i)
                    self.assertEqual(no1.name, no2.name)
                    self.assertEqual(no1.publicId, no2.publicId)
                    self.assertEqual(no1.systemId, no2.systemId)
                    stack.append((no1, no2))
                for i in range(len(n1.entities)):
                    e1 = n1.entities.item(i)
                    e2 = n2.entities.item(i)
                    self.assertEqual(e1.notationName, e2.notationName)
                    self.assertEqual(e1.publicId, e2.publicId)
                    self.assertEqual(e1.systemId, e2.systemId)
                    stack.append((e1, e2))
            if n1.nodeType != Node.DOCUMENT_NODE:
                self.assertTrue(n1.ownerDocument.isSameNode(doc))
                self.assertTrue(n2.ownerDocument.isSameNode(doc2))
            for i in range(len(n1.childNodes)):
                stack.append((n1.childNodes[i], n2.childNodes[i]))

    def testPickledDocument(self):
        doc = parseString(sample)
        for proto in range(2, pickle.HIGHEST_PROTOCOL + 1):
            s = pickle.dumps(doc, proto)
            doc2 = pickle.loads(s)
            self.assert_recursive_equal(doc, doc2)

    def testDeepcopiedDocument(self):
        doc = parseString(sample)
        doc2 = copy.deepcopy(doc)
        self.assert_recursive_equal(doc, doc2)

    def testSerializeCommentNodeWithDoubleHyphen(self):
        doc = create_doc_without_doctype()
        doc.appendChild(doc.createComment("foo--bar"))
        self.assertRaises(ValueError, doc.toxml)


    def testEmptyXMLNSValue(self):
        doc = parseString("<element xmlns=''>\n"
                          "<foo/>\n</element>")
        doc2 = parseString(doc.toxml())
        self.confirm(doc2.namespaceURI == xml.dom.EMPTY_NAMESPACE)

    def testExceptionOnSpacesInXMLNSValue(self):
        with self.assertRaises((ValueError, ExpatError)):
            parseString(
                '<element xmlns:abc="http:abc.com/de f g/hi/j k">' +
                '<abc:foo /></element>'
            )

    def testDocRemoveChild(self):
        doc = parse(tstfile)
        title_tag = doc.documentElement.getElementsByTagName("TITLE")[0]
        self.assertRaises( xml.dom.NotFoundErr, doc.removeChild, title_tag)
        num_children_before = len(doc.childNodes)
        doc.removeChild(doc.childNodes[0])
        num_children_after = len(doc.childNodes)
        self.assertTrue(num_children_after == num_children_before - 1)

    def testProcessingInstructionNameError(self):
        # wrong variable in .nodeValue property will
        # lead to "NameError: name 'data' is not defined"
        doc = parse(tstfile)
        pi = doc.createProcessingInstruction("y", "z")
        pi.nodeValue = "crash"

    def test_minidom_attribute_order(self):
        xml_str = '<?xml version="1.0" ?><curriculum status="public" company="example"/>'
        doc = parseString(xml_str)
        output = io.StringIO()
        doc.writexml(output)
        self.assertEqual(output.getvalue(), xml_str)

    def test_toxml_with_attributes_ordered(self):
        xml_str = '<?xml version="1.0" ?><curriculum status="public" company="example"/>'
        doc = parseString(xml_str)
        self.assertEqual(doc.toxml(), xml_str)

    def test_toprettyxml_with_attributes_ordered(self):
        xml_str = '<?xml version="1.0" ?><curriculum status="public" company="example"/>'
        doc = parseString(xml_str)
        self.assertEqual(doc.toprettyxml(),
                         '<?xml version="1.0" ?>\n'
                         '<curriculum status="public" company="example"/>\n')

    def test_toprettyxml_with_cdata(self):
        xml_str = '<?xml version="1.0" ?><root><node><![CDATA[</data>]]></node></root>'
        doc = parseString(xml_str)
        self.assertEqual(doc.toprettyxml(),
                         '<?xml version="1.0" ?>\n'
                         '<root>\n'
                         '\t<node><![CDATA[</data>]]></node>\n'
                         '</root>\n')

    def test_cdata_parsing(self):
        xml_str = '<?xml version="1.0" ?><root><node><![CDATA[</data>]]></node></root>'
        dom1 = parseString(xml_str)
        self.checkWholeText(dom1.getElementsByTagName('node')[0].firstChild, '</data>')
        dom2 = parseString(dom1.toprettyxml())
        self.checkWholeText(dom2.getElementsByTagName('node')[0].firstChild, '</data>')

if __name__ == "__main__":
    unittest.main()
from test.support import (
    requires, _2G, _4G, gc_collect, cpython_only, is_emscripten
)
from test.support.import_helper import import_module
from test.support.os_helper import TESTFN, unlink
import unittest
import os
import re
import itertools
import random
import socket
import string
import sys
import weakref

# Skip test if we can't import mmap.
mmap = import_module('mmap')

PAGESIZE = mmap.PAGESIZE

tagname_prefix = f'python_{os.getpid()}_test_mmap'
def random_tagname(length=10):
    suffix = ''.join(random.choices(string.ascii_uppercase, k=length))
    return f'{tagname_prefix}_{suffix}'

# Python's mmap module dup()s the file descriptor. Emscripten's FS layer
# does not materialize file changes through a dupped fd to a new mmap.
if is_emscripten:
    raise unittest.SkipTest("incompatible with Emscripten's mmap emulation.")


class MmapTests(unittest.TestCase):

    def setUp(self):
        if os.path.exists(TESTFN):
            os.unlink(TESTFN)

    def tearDown(self):
        try:
            os.unlink(TESTFN)
        except OSError:
            pass

    def test_basic(self):
        # Test mmap module on Unix systems and Windows

        # Create a file to be mmap'ed.
        f = open(TESTFN, 'bw+')
        try:
            # Write 2 pages worth of data to the file
            f.write(b'\0'* PAGESIZE)
            f.write(b'foo')
            f.write(b'\0'* (PAGESIZE-3) )
            f.flush()
            m = mmap.mmap(f.fileno(), 2 * PAGESIZE)
        finally:
            f.close()

        # Simple sanity checks

        tp = str(type(m))  # SF bug 128713:  segfaulted on Linux
        self.assertEqual(m.find(b'foo'), PAGESIZE)

        self.assertEqual(len(m), 2*PAGESIZE)

        self.assertEqual(m[0], 0)
        self.assertEqual(m[0:3], b'\0\0\0')

        # Shouldn't crash on boundary (Issue #5292)
        self.assertRaises(IndexError, m.__getitem__, len(m))
        self.assertRaises(IndexError, m.__setitem__, len(m), b'\0')

        # Modify the file's content
        m[0] = b'3'[0]
        m[PAGESIZE +3: PAGESIZE +3+3] = b'bar'

        # Check that the modification worked
        self.assertEqual(m[0], b'3'[0])
        self.assertEqual(m[0:3], b'3\0\0')
        self.assertEqual(m[PAGESIZE-1 : PAGESIZE + 7], b'\0foobar\0')

        m.flush()

        # Test doing a regular expression match in an mmap'ed file
        match = re.search(b'[A-Za-z]+', m)
        if match is None:
            self.fail('regex match on mmap failed!')
        else:
            start, end = match.span(0)
            length = end - start

            self.assertEqual(start, PAGESIZE)
            self.assertEqual(end, PAGESIZE + 6)

        # test seeking around (try to overflow the seek implementation)
        m.seek(0,0)
        self.assertEqual(m.tell(), 0)
        m.seek(42,1)
        self.assertEqual(m.tell(), 42)
        m.seek(0,2)
        self.assertEqual(m.tell(), len(m))

        # Try to seek to negative position...
        self.assertRaises(ValueError, m.seek, -1)

        # Try to seek beyond end of mmap...
        self.assertRaises(ValueError, m.seek, 1, 2)

        # Try to seek to negative position...
        self.assertRaises(ValueError, m.seek, -len(m)-1, 2)

        # Try resizing map
        try:
            m.resize(512)
        except SystemError:
            # resize() not supported
            # No messages are printed, since the output of this test suite
            # would then be different across platforms.
            pass
        else:
            # resize() is supported
            self.assertEqual(len(m), 512)
            # Check that we can no longer seek beyond the new size.
            self.assertRaises(ValueError, m.seek, 513, 0)

            # Check that the underlying file is truncated too
            # (bug #728515)
            f = open(TESTFN, 'rb')
            try:
                f.seek(0, 2)
                self.assertEqual(f.tell(), 512)
            finally:
                f.close()
            self.assertEqual(m.size(), 512)

        m.close()

    def test_access_parameter(self):
        # Test for "access" keyword parameter
        mapsize = 10
        with open(TESTFN, "wb") as fp:
            fp.write(b"a"*mapsize)
        with open(TESTFN, "rb") as f:
            m = mmap.mmap(f.fileno(), mapsize, access=mmap.ACCESS_READ)
            self.assertEqual(m[:], b'a'*mapsize, "Readonly memory map data incorrect.")

            # Ensuring that readonly mmap can't be slice assigned
            try:
                m[:] = b'b'*mapsize
            except TypeError:
                pass
            else:
                self.fail("Able to write to readonly memory map")

            # Ensuring that readonly mmap can't be item assigned
            try:
                m[0] = b'b'
            except TypeError:
                pass
            else:
                self.fail("Able to write to readonly memory map")

            # Ensuring that readonly mmap can't be write() to
            try:
                m.seek(0,0)
                m.write(b'abc')
            except TypeError:
                pass
            else:
                self.fail("Able to write to readonly memory map")

            # Ensuring that readonly mmap can't be write_byte() to
            try:
                m.seek(0,0)
                m.write_byte(b'd')
            except TypeError:
                pass
            else:
                self.fail("Able to write to readonly memory map")

            # Ensuring that readonly mmap can't be resized
            try:
                m.resize(2*mapsize)
            except SystemError:   # resize is not universally supported
                pass
            except TypeError:
                pass
            else:
                self.fail("Able to resize readonly memory map")
            with open(TESTFN, "rb") as fp:
                self.assertEqual(fp.read(), b'a'*mapsize,
                                 "Readonly memory map data file was modified")

        # Opening mmap with size too big
        with open(TESTFN, "r+b") as f:
            try:
                m = mmap.mmap(f.fileno(), mapsize+1)
            except ValueError:
                # we do not expect a ValueError on Windows
                # CAUTION:  This also changes the size of the file on disk, and
                # later tests assume that the length hasn't changed.  We need to
                # repair that.
                if sys.platform.startswith('win'):
                    self.fail("Opening mmap with size+1 should work on Windows.")
            else:
                # we expect a ValueError on Unix, but not on Windows
                if not sys.platform.startswith('win'):
                    self.fail("Opening mmap with size+1 should raise ValueError.")
                m.close()
            if sys.platform.startswith('win'):
                # Repair damage from the resizing test.
                with open(TESTFN, 'r+b') as f:
                    f.truncate(mapsize)

        # Opening mmap with access=ACCESS_WRITE
        with open(TESTFN, "r+b") as f:
            m = mmap.mmap(f.fileno(), mapsize, access=mmap.ACCESS_WRITE)
            # Modifying write-through memory map
            m[:] = b'c'*mapsize
            self.assertEqual(m[:], b'c'*mapsize,
                   "Write-through memory map memory not updated properly.")
            m.flush()
            m.close()
        with open(TESTFN, 'rb') as f:
            stuff = f.read()
        self.assertEqual(stuff, b'c'*mapsize,
               "Write-through memory map data file not updated properly.")

        # Opening mmap with access=ACCESS_COPY
        with open(TESTFN, "r+b") as f:
            m = mmap.mmap(f.fileno(), mapsize, access=mmap.ACCESS_COPY)
            # Modifying copy-on-write memory map
            m[:] = b'd'*mapsize
            self.assertEqual(m[:], b'd' * mapsize,
                             "Copy-on-write memory map data not written correctly.")
            m.flush()
            with open(TESTFN, "rb") as fp:
                self.assertEqual(fp.read(), b'c'*mapsize,
                                 "Copy-on-write test data file should not be modified.")
            # Ensuring copy-on-write maps cannot be resized
            self.assertRaises(TypeError, m.resize, 2*mapsize)
            m.close()

        # Ensuring invalid access parameter raises exception
        with open(TESTFN, "r+b") as f:
            self.assertRaises(ValueError, mmap.mmap, f.fileno(), mapsize, access=4)

        if os.name == "posix":
            # Try incompatible flags, prot and access parameters.
            with open(TESTFN, "r+b") as f:
                self.assertRaises(ValueError, mmap.mmap, f.fileno(), mapsize,
                                  flags=mmap.MAP_PRIVATE,
                                  prot=mmap.PROT_READ, access=mmap.ACCESS_WRITE)

            # Try writing with PROT_EXEC and without PROT_WRITE
            prot = mmap.PROT_READ | getattr(mmap, 'PROT_EXEC', 0)
            with open(TESTFN, "r+b") as f:
                m = mmap.mmap(f.fileno(), mapsize, prot=prot)
                self.assertRaises(TypeError, m.write, b"abcdef")
                self.assertRaises(TypeError, m.write_byte, 0)
                m.close()

    def test_bad_file_desc(self):
        # Try opening a bad file descriptor...
        self.assertRaises(OSError, mmap.mmap, -2, 4096)

    def test_tougher_find(self):
        # Do a tougher .find() test.  SF bug 515943 pointed out that, in 2.2,
        # searching for data with embedded \0 bytes didn't work.
        with open(TESTFN, 'wb+') as f:

            data = b'aabaac\x00deef\x00\x00aa\x00'
            n = len(data)
            f.write(data)
            f.flush()
            m = mmap.mmap(f.fileno(), n)

        for start in range(n+1):
            for finish in range(start, n+1):
                slice = data[start : finish]
                self.assertEqual(m.find(slice), data.find(slice))
                self.assertEqual(m.find(slice + b'x'), -1)
        m.close()

    def test_find_end(self):
        # test the new 'end' parameter works as expected
        with open(TESTFN, 'wb+') as f:
            data = b'one two ones'
            n = len(data)
            f.write(data)
            f.flush()
            m = mmap.mmap(f.fileno(), n)

        self.assertEqual(m.find(b'one'), 0)
        self.assertEqual(m.find(b'ones'), 8)
        self.assertEqual(m.find(b'one', 0, -1), 0)
        self.assertEqual(m.find(b'one', 1), 8)
        self.assertEqual(m.find(b'one', 1, -1), 8)
        self.assertEqual(m.find(b'one', 1, -2), -1)
        self.assertEqual(m.find(bytearray(b'one')), 0)


    def test_rfind(self):
        # test the new 'end' parameter works as expected
        with open(TESTFN, 'wb+') as f:
            data = b'one two ones'
            n = len(data)
            f.write(data)
            f.flush()
            m = mmap.mmap(f.fileno(), n)

        self.assertEqual(m.rfind(b'one'), 8)
        self.assertEqual(m.rfind(b'one '), 0)
        self.assertEqual(m.rfind(b'one', 0, -1), 8)
        self.assertEqual(m.rfind(b'one', 0, -2), 0)
        self.assertEqual(m.rfind(b'one', 1, -1), 8)
        self.assertEqual(m.rfind(b'one', 1, -2), -1)
        self.assertEqual(m.rfind(bytearray(b'one')), 8)


    def test_double_close(self):
        # make sure a double close doesn't crash on Solaris (Bug# 665913)
        with open(TESTFN, 'wb+') as f:
            f.write(2**16 * b'a') # Arbitrary character

        with open(TESTFN, 'rb') as f:
            mf = mmap.mmap(f.fileno(), 2**16, access=mmap.ACCESS_READ)
            mf.close()
            mf.close()

    def test_entire_file(self):
        # test mapping of entire file by passing 0 for map length
        with open(TESTFN, "wb+") as f:
            f.write(2**16 * b'm') # Arbitrary character

        with open(TESTFN, "rb+") as f, \
             mmap.mmap(f.fileno(), 0) as mf:
            self.assertEqual(len(mf), 2**16, "Map size should equal file size.")
            self.assertEqual(mf.read(2**16), 2**16 * b"m")

    def test_length_0_offset(self):
        # Issue #10916: test mapping of remainder of file by passing 0 for
        # map length with an offset doesn't cause a segfault.
        # NOTE: allocation granularity is currently 65536 under Win64,
        # and therefore the minimum offset alignment.
        with open(TESTFN, "wb") as f:
            f.write((65536 * 2) * b'm') # Arbitrary character

        with open(TESTFN, "rb") as f:
            with mmap.mmap(f.fileno(), 0, offset=65536, access=mmap.ACCESS_READ) as mf:
                self.assertRaises(IndexError, mf.__getitem__, 80000)

    def test_length_0_large_offset(self):
        # Issue #10959: test mapping of a file by passing 0 for
        # map length with a large offset doesn't cause a segfault.
        with open(TESTFN, "wb") as f:
            f.write(115699 * b'm') # Arbitrary character

        with open(TESTFN, "w+b") as f:
            self.assertRaises(ValueError, mmap.mmap, f.fileno(), 0,
                              offset=2147418112)

    def test_move(self):
        # make move works everywhere (64-bit format problem earlier)
        with open(TESTFN, 'wb+') as f:

            f.write(b"ABCDEabcde") # Arbitrary character
            f.flush()

            mf = mmap.mmap(f.fileno(), 10)
            mf.move(5, 0, 5)
            self.assertEqual(mf[:], b"ABCDEABCDE", "Map move should have duplicated front 5")
            mf.close()

        # more excessive test
        data = b"0123456789"
        for dest in range(len(data)):
            for src in range(len(data)):
                for count in range(len(data) - max(dest, src)):
                    expected = data[:dest] + data[src:src+count] + data[dest+count:]
                    m = mmap.mmap(-1, len(data))
                    m[:] = data
                    m.move(dest, src, count)
                    self.assertEqual(m[:], expected)
                    m.close()

        # segfault test (Issue 5387)
        m = mmap.mmap(-1, 100)
        offsets = [-100, -1, 0, 1, 100]
        for source, dest, size in itertools.product(offsets, offsets, offsets):
            try:
                m.move(source, dest, size)
            except ValueError:
                pass

        offsets = [(-1, -1, -1), (-1, -1, 0), (-1, 0, -1), (0, -1, -1),
                   (-1, 0, 0), (0, -1, 0), (0, 0, -1)]
        for source, dest, size in offsets:
            self.assertRaises(ValueError, m.move, source, dest, size)

        m.close()

        m = mmap.mmap(-1, 1) # single byte
        self.assertRaises(ValueError, m.move, 0, 0, 2)
        self.assertRaises(ValueError, m.move, 1, 0, 1)
        self.assertRaises(ValueError, m.move, 0, 1, 1)
        m.move(0, 0, 1)
        m.move(0, 0, 0)


    def test_anonymous(self):
        # anonymous mmap.mmap(-1, PAGE)
        m = mmap.mmap(-1, PAGESIZE)
        for x in range(PAGESIZE):
            self.assertEqual(m[x], 0,
                             "anonymously mmap'ed contents should be zero")

        for x in range(PAGESIZE):
            b = x & 0xff
            m[x] = b
            self.assertEqual(m[x], b)

    def test_read_all(self):
        m = mmap.mmap(-1, 16)
        self.addCleanup(m.close)

        # With no parameters, or None or a negative argument, reads all
        m.write(bytes(range(16)))
        m.seek(0)
        self.assertEqual(m.read(), bytes(range(16)))
        m.seek(8)
        self.assertEqual(m.read(), bytes(range(8, 16)))
        m.seek(16)
        self.assertEqual(m.read(), b'')
        m.seek(3)
        self.assertEqual(m.read(None), bytes(range(3, 16)))
        m.seek(4)
        self.assertEqual(m.read(-1), bytes(range(4, 16)))
        m.seek(5)
        self.assertEqual(m.read(-2), bytes(range(5, 16)))
        m.seek(9)
        self.assertEqual(m.read(-42), bytes(range(9, 16)))

    def test_read_invalid_arg(self):
        m = mmap.mmap(-1, 16)
        self.addCleanup(m.close)

        self.assertRaises(TypeError, m.read, 'foo')
        self.assertRaises(TypeError, m.read, 5.5)
        self.assertRaises(TypeError, m.read, [1, 2, 3])

    def test_extended_getslice(self):
        # Test extended slicing by comparing with list slicing.
        s = bytes(reversed(range(256)))
        m = mmap.mmap(-1, len(s))
        m[:] = s
        self.assertEqual(m[:], s)
        indices = (0, None, 1, 3, 19, 300, sys.maxsize, -1, -2, -31, -300)
        for start in indices:
            for stop in indices:
                # Skip step 0 (invalid)
                for step in indices[1:]:
                    self.assertEqual(m[start:stop:step],
                                     s[start:stop:step])

    def test_extended_set_del_slice(self):
        # Test extended slicing by comparing with list slicing.
        s = bytes(reversed(range(256)))
        m = mmap.mmap(-1, len(s))
        indices = (0, None, 1, 3, 19, 300, sys.maxsize, -1, -2, -31, -300)
        for start in indices:
            for stop in indices:
                # Skip invalid step 0
                for step in indices[1:]:
                    m[:] = s
                    self.assertEqual(m[:], s)
                    L = list(s)
                    # Make sure we have a slice of exactly the right length,
                    # but with different data.
                    data = L[start:stop:step]
                    data = bytes(reversed(data))
                    L[start:stop:step] = data
                    m[start:stop:step] = data
                    self.assertEqual(m[:], bytes(L))

    def make_mmap_file (self, f, halfsize):
        # Write 2 pages worth of data to the file
        f.write (b'\0' * halfsize)
        f.write (b'foo')
        f.write (b'\0' * (halfsize - 3))
        f.flush ()
        return mmap.mmap (f.fileno(), 0)

    def test_empty_file (self):
        f = open (TESTFN, 'w+b')
        f.close()
        with open(TESTFN, "rb") as f :
            self.assertRaisesRegex(ValueError,
                                   "cannot mmap an empty file",
                                   mmap.mmap, f.fileno(), 0,
                                   access=mmap.ACCESS_READ)

    def test_offset (self):
        f = open (TESTFN, 'w+b')

        try: # unlink TESTFN no matter what
            halfsize = mmap.ALLOCATIONGRANULARITY
            m = self.make_mmap_file (f, halfsize)
            m.close ()
            f.close ()

            mapsize = halfsize * 2
            # Try invalid offset
            f = open(TESTFN, "r+b")
            for offset in [-2, -1, None]:
                try:
                    m = mmap.mmap(f.fileno(), mapsize, offset=offset)
                    self.assertEqual(0, 1)
                except (ValueError, TypeError, OverflowError):
                    pass
                else:
                    self.assertEqual(0, 0)
            f.close()

            # Try valid offset, hopefully 8192 works on all OSes
            f = open(TESTFN, "r+b")
            m = mmap.mmap(f.fileno(), mapsize - halfsize, offset=halfsize)
            self.assertEqual(m[0:3], b'foo')
            f.close()

            # Try resizing map
            try:
                m.resize(512)
            except SystemError:
                pass
            else:
                # resize() is supported
                self.assertEqual(len(m), 512)
                # Check that we can no longer seek beyond the new size.
                self.assertRaises(ValueError, m.seek, 513, 0)
                # Check that the content is not changed
                self.assertEqual(m[0:3], b'foo')

                # Check that the underlying file is truncated too
                f = open(TESTFN, 'rb')
                f.seek(0, 2)
                self.assertEqual(f.tell(), halfsize + 512)
                f.close()
                self.assertEqual(m.size(), halfsize + 512)

            m.close()

        finally:
            f.close()
            try:
                os.unlink(TESTFN)
            except OSError:
                pass

    def test_subclass(self):
        class anon_mmap(mmap.mmap):
            def __new__(klass, *args, **kwargs):
                return mmap.mmap.__new__(klass, -1, *args, **kwargs)
        anon_mmap(PAGESIZE)

    @unittest.skipUnless(hasattr(mmap, 'PROT_READ'), "needs mmap.PROT_READ")
    def test_prot_readonly(self):
        mapsize = 10
        with open(TESTFN, "wb") as fp:
            fp.write(b"a"*mapsize)
        with open(TESTFN, "rb") as f:
            m = mmap.mmap(f.fileno(), mapsize, prot=mmap.PROT_READ)
            self.assertRaises(TypeError, m.write, "foo")

    def test_error(self):
        self.assertIs(mmap.error, OSError)

    def test_io_methods(self):
        data = b"0123456789"
        with open(TESTFN, "wb") as fp:
            fp.write(b"x"*len(data))
        with open(TESTFN, "r+b") as f:
            m = mmap.mmap(f.fileno(), len(data))
        # Test write_byte()
        for i in range(len(data)):
            self.assertEqual(m.tell(), i)
            m.write_byte(data[i])
            self.assertEqual(m.tell(), i+1)
        self.assertRaises(ValueError, m.write_byte, b"x"[0])
        self.assertEqual(m[:], data)
        # Test read_byte()
        m.seek(0)
        for i in range(len(data)):
            self.assertEqual(m.tell(), i)
            self.assertEqual(m.read_byte(), data[i])
            self.assertEqual(m.tell(), i+1)
        self.assertRaises(ValueError, m.read_byte)
        # Test read()
        m.seek(3)
        self.assertEqual(m.read(3), b"345")
        self.assertEqual(m.tell(), 6)
        # Test write()
        m.seek(3)
        m.write(b"bar")
        self.assertEqual(m.tell(), 6)
        self.assertEqual(m[:], b"012bar6789")
        m.write(bytearray(b"baz"))
        self.assertEqual(m.tell(), 9)
        self.assertEqual(m[:], b"012barbaz9")
        self.assertRaises(ValueError, m.write, b"ba")

    def test_non_ascii_byte(self):
        for b in (129, 200, 255): # > 128
            m = mmap.mmap(-1, 1)
            m.write_byte(b)
            self.assertEqual(m[0], b)
            m.seek(0)
            self.assertEqual(m.read_byte(), b)
            m.close()

    @unittest.skipUnless(os.name == 'nt', 'requires Windows')
    def test_tagname(self):
        data1 = b"0123456789"
        data2 = b"abcdefghij"
        assert len(data1) == len(data2)
        tagname1 = random_tagname()
        tagname2 = random_tagname()

        # Test same tag
        m1 = mmap.mmap(-1, len(data1), tagname=tagname1)
        m1[:] = data1
        m2 = mmap.mmap(-1, len(data2), tagname=tagname1)
        m2[:] = data2
        self.assertEqual(m1[:], data2)
        self.assertEqual(m2[:], data2)
        m2.close()
        m1.close()

        # Test different tag
        m1 = mmap.mmap(-1, len(data1), tagname=tagname1)
        m1[:] = data1
        m2 = mmap.mmap(-1, len(data2), tagname=tagname2)
        m2[:] = data2
        self.assertEqual(m1[:], data1)
        self.assertEqual(m2[:], data2)
        m2.close()
        m1.close()

    @cpython_only
    @unittest.skipUnless(os.name == 'nt', 'requires Windows')
    def test_sizeof(self):
        m1 = mmap.mmap(-1, 100)
        tagname = random_tagname()
        m2 = mmap.mmap(-1, 100, tagname=tagname)
        self.assertEqual(sys.getsizeof(m2),
                         sys.getsizeof(m1) + len(tagname) + 1)

    @unittest.skipUnless(os.name == 'nt', 'requires Windows')
    def test_crasher_on_windows(self):
        # Should not crash (Issue 1733986)
        tagname = random_tagname()
        m = mmap.mmap(-1, 1000, tagname=tagname)
        try:
            mmap.mmap(-1, 5000, tagname=tagname)[:] # same tagname, but larger size
        except:
            pass
        m.close()

        # Should not crash (Issue 5385)
        with open(TESTFN, "wb") as fp:
            fp.write(b"x"*10)
        f = open(TESTFN, "r+b")
        m = mmap.mmap(f.fileno(), 0)
        f.close()
        try:
            m.resize(0) # will raise OSError
        except:
            pass
        try:
            m[:]
        except:
            pass
        m.close()

    @unittest.skipUnless(os.name == 'nt', 'requires Windows')
    def test_invalid_descriptor(self):
        # socket file descriptors are valid, but out of range
        # for _get_osfhandle, causing a crash when validating the
        # parameters to _get_osfhandle.
        s = socket.socket()
        try:
            with self.assertRaises(OSError):
                m = mmap.mmap(s.fileno(), 10)
        finally:
            s.close()

    def test_context_manager(self):
        with mmap.mmap(-1, 10) as m:
            self.assertFalse(m.closed)
        self.assertTrue(m.closed)

    def test_context_manager_exception(self):
        # Test that the OSError gets passed through
        with self.assertRaises(Exception) as exc:
            with mmap.mmap(-1, 10) as m:
                raise OSError
        self.assertIsInstance(exc.exception, OSError,
                              "wrong exception raised in context manager")
        self.assertTrue(m.closed, "context manager failed")

    def test_weakref(self):
        # Check mmap objects are weakrefable
        mm = mmap.mmap(-1, 16)
        wr = weakref.ref(mm)
        self.assertIs(wr(), mm)
        del mm
        gc_collect()
        self.assertIs(wr(), None)

    def test_write_returning_the_number_of_bytes_written(self):
        mm = mmap.mmap(-1, 16)
        self.assertEqual(mm.write(b""), 0)
        self.assertEqual(mm.write(b"x"), 1)
        self.assertEqual(mm.write(b"yz"), 2)
        self.assertEqual(mm.write(b"python"), 6)

    def test_resize_past_pos(self):
        m = mmap.mmap(-1, 8192)
        self.addCleanup(m.close)
        m.read(5000)
        try:
            m.resize(4096)
        except SystemError:
            self.skipTest("resizing not supported")
        self.assertEqual(m.read(14), b'')
        self.assertRaises(ValueError, m.read_byte)
        self.assertRaises(ValueError, m.write_byte, 42)
        self.assertRaises(ValueError, m.write, b'abc')

    def test_concat_repeat_exception(self):
        m = mmap.mmap(-1, 16)
        with self.assertRaises(TypeError):
            m + m
        with self.assertRaises(TypeError):
            m * 2

    def test_flush_return_value(self):
        # mm.flush() should return None on success, raise an
        # exception on error under all platforms.
        mm = mmap.mmap(-1, 16)
        self.addCleanup(mm.close)
        mm.write(b'python')
        result = mm.flush()
        self.assertIsNone(result)
        if sys.platform.startswith('linux'):
            # 'offset' must be a multiple of mmap.PAGESIZE on Linux.
            # See bpo-34754 for details.
            self.assertRaises(OSError, mm.flush, 1, len(b'python'))

    def test_repr(self):
        open_mmap_repr_pat = re.compile(
            r"<mmap.mmap closed=False, "
            r"access=(?P<access>\S+), "
            r"length=(?P<length>\d+), "
            r"pos=(?P<pos>\d+), "
            r"offset=(?P<offset>\d+)>")
        closed_mmap_repr_pat = re.compile(r"<mmap.mmap closed=True>")
        mapsizes = (50, 100, 1_000, 1_000_000, 10_000_000)
        offsets = tuple((mapsize // 2 // mmap.ALLOCATIONGRANULARITY)
                        * mmap.ALLOCATIONGRANULARITY for mapsize in mapsizes)
        for offset, mapsize in zip(offsets, mapsizes):
            data = b'a' * mapsize
            length = mapsize - offset
            accesses = ('ACCESS_DEFAULT', 'ACCESS_READ',
                        'ACCESS_COPY', 'ACCESS_WRITE')
            positions = (0, length//10, length//5, length//4)
            with open(TESTFN, "wb+") as fp:
                fp.write(data)
                fp.flush()
                for access, pos in itertools.product(accesses, positions):
                    accint = getattr(mmap, access)
                    with mmap.mmap(fp.fileno(),
                                   length,
                                   access=accint,
                                   offset=offset) as mm:
                        mm.seek(pos)
                        match = open_mmap_repr_pat.match(repr(mm))
                        self.assertIsNotNone(match)
                        self.assertEqual(match.group('access'), access)
                        self.assertEqual(match.group('length'), str(length))
                        self.assertEqual(match.group('pos'), str(pos))
                        self.assertEqual(match.group('offset'), str(offset))
                    match = closed_mmap_repr_pat.match(repr(mm))
                    self.assertIsNotNone(match)

    @unittest.skipUnless(hasattr(mmap.mmap, 'madvise'), 'needs madvise')
    def test_madvise(self):
        size = 2 * PAGESIZE
        m = mmap.mmap(-1, size)

        with self.assertRaisesRegex(ValueError, "madvise start out of bounds"):
            m.madvise(mmap.MADV_NORMAL, size)
        with self.assertRaisesRegex(ValueError, "madvise start out of bounds"):
            m.madvise(mmap.MADV_NORMAL, -1)
        with self.assertRaisesRegex(ValueError, "madvise length invalid"):
            m.madvise(mmap.MADV_NORMAL, 0, -1)
        with self.assertRaisesRegex(OverflowError, "madvise length too large"):
            m.madvise(mmap.MADV_NORMAL, PAGESIZE, sys.maxsize)
        self.assertEqual(m.madvise(mmap.MADV_NORMAL), None)
        self.assertEqual(m.madvise(mmap.MADV_NORMAL, PAGESIZE), None)
        self.assertEqual(m.madvise(mmap.MADV_NORMAL, PAGESIZE, size), None)
        self.assertEqual(m.madvise(mmap.MADV_NORMAL, 0, 2), None)
        self.assertEqual(m.madvise(mmap.MADV_NORMAL, 0, size), None)

    @unittest.skipUnless(os.name == 'nt', 'requires Windows')
    def test_resize_up_when_mapped_to_pagefile(self):
        """If the mmap is backed by the pagefile ensure a resize up can happen
        and that the original data is still in place
        """
        start_size = PAGESIZE
        new_size = 2 * start_size
        data = bytes(random.getrandbits(8) for _ in range(start_size))

        m = mmap.mmap(-1, start_size)
        m[:] = data
        m.resize(new_size)
        self.assertEqual(len(m), new_size)
        self.assertEqual(m[:start_size], data[:start_size])

    @unittest.skipUnless(os.name == 'nt', 'requires Windows')
    def test_resize_down_when_mapped_to_pagefile(self):
        """If the mmap is backed by the pagefile ensure a resize down up can happen
        and that a truncated form of the original data is still in place
        """
        start_size = PAGESIZE
        new_size = start_size // 2
        data = bytes(random.getrandbits(8) for _ in range(start_size))

        m = mmap.mmap(-1, start_size)
        m[:] = data
        m.resize(new_size)
        self.assertEqual(len(m), new_size)
        self.assertEqual(m[:new_size], data[:new_size])

    @unittest.skipUnless(os.name == 'nt', 'requires Windows')
    def test_resize_fails_if_mapping_held_elsewhere(self):
        """If more than one mapping is held against a named file on Windows, neither
        mapping can be resized
        """
        start_size = 2 * PAGESIZE
        reduced_size = PAGESIZE

        f = open(TESTFN, 'wb+')
        f.truncate(start_size)
        try:
            m1 = mmap.mmap(f.fileno(), start_size)
            m2 = mmap.mmap(f.fileno(), start_size)
            with self.assertRaises(OSError):
                m1.resize(reduced_size)
            with self.assertRaises(OSError):
                m2.resize(reduced_size)
            m2.close()
            m1.resize(reduced_size)
            self.assertEqual(m1.size(), reduced_size)
            self.assertEqual(os.stat(f.fileno()).st_size, reduced_size)
        finally:
            f.close()

    @unittest.skipUnless(os.name == 'nt', 'requires Windows')
    def test_resize_succeeds_with_error_for_second_named_mapping(self):
        """If a more than one mapping exists of the same name, none of them can
        be resized: they'll raise an Exception and leave the original mapping intact
        """
        start_size = 2 * PAGESIZE
        reduced_size = PAGESIZE
        tagname =  random_tagname()
        data_length = 8
        data = bytes(random.getrandbits(8) for _ in range(data_length))

        m1 = mmap.mmap(-1, start_size, tagname=tagname)
        m2 = mmap.mmap(-1, start_size, tagname=tagname)
        m1[:data_length] = data
        self.assertEqual(m2[:data_length], data)
        with self.assertRaises(OSError):
            m1.resize(reduced_size)
        self.assertEqual(m1.size(), start_size)
        self.assertEqual(m1[:data_length], data)
        self.assertEqual(m2[:data_length], data)

class LargeMmapTests(unittest.TestCase):

    def setUp(self):
        unlink(TESTFN)

    def tearDown(self):
        unlink(TESTFN)

    def _make_test_file(self, num_zeroes, tail):
        if sys.platform[:3] == 'win' or sys.platform == 'darwin':
            requires('largefile',
                'test requires %s bytes and a long time to run' % str(0x180000000))
        f = open(TESTFN, 'w+b')
        try:
            f.seek(num_zeroes)
            f.write(tail)
            f.flush()
        except (OSError, OverflowError, ValueError):
            try:
                f.close()
            except (OSError, OverflowError):
                pass
            raise unittest.SkipTest("filesystem does not have largefile support")
        return f

    def test_large_offset(self):
        with self._make_test_file(0x14FFFFFFF, b" ") as f:
            with mmap.mmap(f.fileno(), 0, offset=0x140000000, access=mmap.ACCESS_READ) as m:
                self.assertEqual(m[0xFFFFFFF], 32)

    def test_large_filesize(self):
        with self._make_test_file(0x17FFFFFFF, b" ") as f:
            if sys.maxsize < 0x180000000:
                # On 32 bit platforms the file is larger than sys.maxsize so
                # mapping the whole file should fail -- Issue #16743
                with self.assertRaises(OverflowError):
                    mmap.mmap(f.fileno(), 0x180000000, access=mmap.ACCESS_READ)
                with self.assertRaises(ValueError):
                    mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
            with mmap.mmap(f.fileno(), 0x10000, access=mmap.ACCESS_READ) as m:
                self.assertEqual(m.size(), 0x180000000)

    # Issue 11277: mmap() with large (~4 GiB) sparse files crashes on OS X.

    def _test_around_boundary(self, boundary):
        tail = b'  DEARdear  '
        start = boundary - len(tail) // 2
        end = start + len(tail)
        with self._make_test_file(start, tail) as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
                self.assertEqual(m[start:end], tail)

    @unittest.skipUnless(sys.maxsize > _4G, "test cannot run on 32-bit systems")
    def test_around_2GB(self):
        self._test_around_boundary(_2G)

    @unittest.skipUnless(sys.maxsize > _4G, "test cannot run on 32-bit systems")
    def test_around_4GB(self):
        self._test_around_boundary(_4G)


if __name__ == '__main__':
    unittest.main()
# Test the module type
import unittest
import weakref
from test.support import gc_collect
from test.support import import_helper
from test.support.script_helper import assert_python_ok

import sys
ModuleType = type(sys)


class FullLoader:
    pass


class BareLoader:
    pass


class ModuleTests(unittest.TestCase):
    def test_uninitialized(self):
        # An uninitialized module has no __dict__ or __name__,
        # and __doc__ is None
        foo = ModuleType.__new__(ModuleType)
        self.assertTrue(isinstance(foo.__dict__, dict))
        self.assertEqual(dir(foo), [])
        try:
            s = foo.__name__
            self.fail("__name__ = %s" % repr(s))
        except AttributeError:
            pass
        self.assertEqual(foo.__doc__, ModuleType.__doc__)

    def test_uninitialized_missing_getattr(self):
        # Issue 8297
        # test the text in the AttributeError of an uninitialized module
        foo = ModuleType.__new__(ModuleType)
        self.assertRaisesRegex(
                AttributeError, "module has no attribute 'not_here'",
                getattr, foo, "not_here")

    def test_missing_getattr(self):
        # Issue 8297
        # test the text in the AttributeError
        foo = ModuleType("foo")
        self.assertRaisesRegex(
                AttributeError, "module 'foo' has no attribute 'not_here'",
                getattr, foo, "not_here")

    def test_no_docstring(self):
        # Regularly initialized module, no docstring
        foo = ModuleType("foo")
        self.assertEqual(foo.__name__, "foo")
        self.assertEqual(foo.__doc__, None)
        self.assertIs(foo.__loader__, None)
        self.assertIs(foo.__package__, None)
        self.assertIs(foo.__spec__, None)
        self.assertEqual(foo.__dict__, {"__name__": "foo", "__doc__": None,
                                        "__loader__": None, "__package__": None,
                                        "__spec__": None})

    def test_ascii_docstring(self):
        # ASCII docstring
        foo = ModuleType("foo", "foodoc")
        self.assertEqual(foo.__name__, "foo")
        self.assertEqual(foo.__doc__, "foodoc")
        self.assertEqual(foo.__dict__,
                         {"__name__": "foo", "__doc__": "foodoc",
                          "__loader__": None, "__package__": None,
                          "__spec__": None})

    def test_unicode_docstring(self):
        # Unicode docstring
        foo = ModuleType("foo", "foodoc\u1234")
        self.assertEqual(foo.__name__, "foo")
        self.assertEqual(foo.__doc__, "foodoc\u1234")
        self.assertEqual(foo.__dict__,
                         {"__name__": "foo", "__doc__": "foodoc\u1234",
                          "__loader__": None, "__package__": None,
                          "__spec__": None})

    def test_reinit(self):
        # Reinitialization should not replace the __dict__
        foo = ModuleType("foo", "foodoc\u1234")
        foo.bar = 42
        d = foo.__dict__
        foo.__init__("foo", "foodoc")
        self.assertEqual(foo.__name__, "foo")
        self.assertEqual(foo.__doc__, "foodoc")
        self.assertEqual(foo.bar, 42)
        self.assertEqual(foo.__dict__,
              {"__name__": "foo", "__doc__": "foodoc", "bar": 42,
               "__loader__": None, "__package__": None, "__spec__": None})
        self.assertTrue(foo.__dict__ is d)

    def test_dont_clear_dict(self):
        # See issue 7140.
        def f():
            foo = ModuleType("foo")
            foo.bar = 4
            return foo
        gc_collect()
        self.assertEqual(f().__dict__["bar"], 4)

    def test_clear_dict_in_ref_cycle(self):
        destroyed = []
        m = ModuleType("foo")
        m.destroyed = destroyed
        s = """class A:
    def __init__(self, l):
        self.l = l
    def __del__(self):
        self.l.append(1)
a = A(destroyed)"""
        exec(s, m.__dict__)
        del m
        gc_collect()
        self.assertEqual(destroyed, [1])

    def test_weakref(self):
        m = ModuleType("foo")
        wr = weakref.ref(m)
        self.assertIs(wr(), m)
        del m
        gc_collect()
        self.assertIs(wr(), None)

    def test_module_getattr(self):
        import test.good_getattr as gga
        from test.good_getattr import test
        self.assertEqual(test, "There is test")
        self.assertEqual(gga.x, 1)
        self.assertEqual(gga.y, 2)
        with self.assertRaisesRegex(AttributeError,
                                    "Deprecated, use whatever instead"):
            gga.yolo
        self.assertEqual(gga.whatever, "There is whatever")
        del sys.modules['test.good_getattr']

    def test_module_getattr_errors(self):
        import test.bad_getattr as bga
        from test import bad_getattr2
        self.assertEqual(bga.x, 1)
        self.assertEqual(bad_getattr2.x, 1)
        with self.assertRaises(TypeError):
            bga.nope
        with self.assertRaises(TypeError):
            bad_getattr2.nope
        del sys.modules['test.bad_getattr']
        if 'test.bad_getattr2' in sys.modules:
            del sys.modules['test.bad_getattr2']

    def test_module_dir(self):
        import test.good_getattr as gga
        self.assertEqual(dir(gga), ['a', 'b', 'c'])
        del sys.modules['test.good_getattr']

    def test_module_dir_errors(self):
        import test.bad_getattr as bga
        from test import bad_getattr2
        with self.assertRaises(TypeError):
            dir(bga)
        with self.assertRaises(TypeError):
            dir(bad_getattr2)
        del sys.modules['test.bad_getattr']
        if 'test.bad_getattr2' in sys.modules:
            del sys.modules['test.bad_getattr2']

    def test_module_getattr_tricky(self):
        from test import bad_getattr3
        # these lookups should not crash
        with self.assertRaises(AttributeError):
            bad_getattr3.one
        with self.assertRaises(AttributeError):
            bad_getattr3.delgetattr
        if 'test.bad_getattr3' in sys.modules:
            del sys.modules['test.bad_getattr3']

    def test_module_repr_minimal(self):
        # reprs when modules have no __file__, __name__, or __loader__
        m = ModuleType('foo')
        del m.__name__
        self.assertEqual(repr(m), "<module '?'>")

    def test_module_repr_with_name(self):
        m = ModuleType('foo')
        self.assertEqual(repr(m), "<module 'foo'>")

    def test_module_repr_with_name_and_filename(self):
        m = ModuleType('foo')
        m.__file__ = '/tmp/foo.py'
        self.assertEqual(repr(m), "<module 'foo' from '/tmp/foo.py'>")

    def test_module_repr_with_filename_only(self):
        m = ModuleType('foo')
        del m.__name__
        m.__file__ = '/tmp/foo.py'
        self.assertEqual(repr(m), "<module '?' from '/tmp/foo.py'>")

    def test_module_repr_with_loader_as_None(self):
        m = ModuleType('foo')
        assert m.__loader__ is None
        self.assertEqual(repr(m), "<module 'foo'>")

    def test_module_repr_with_bare_loader_but_no_name(self):
        m = ModuleType('foo')
        del m.__name__
        # Yes, a class not an instance.
        m.__loader__ = BareLoader
        loader_repr = repr(BareLoader)
        self.assertEqual(
            repr(m), "<module '?' ({})>".format(loader_repr))

    def test_module_repr_with_full_loader_but_no_name(self):
        # m.__loader__.module_repr() will fail because the module has no
        # m.__name__.  This exception will get suppressed and instead the
        # loader's repr will be used.
        m = ModuleType('foo')
        del m.__name__
        # Yes, a class not an instance.
        m.__loader__ = FullLoader
        loader_repr = repr(FullLoader)
        self.assertEqual(
            repr(m), "<module '?' ({})>".format(loader_repr))

    def test_module_repr_with_bare_loader(self):
        m = ModuleType('foo')
        # Yes, a class not an instance.
        m.__loader__ = BareLoader
        module_repr = repr(BareLoader)
        self.assertEqual(
            repr(m), "<module 'foo' ({})>".format(module_repr))

    def test_module_repr_with_full_loader(self):
        m = ModuleType('foo')
        # Yes, a class not an instance.
        m.__loader__ = FullLoader
        self.assertEqual(
            repr(m), "<module 'foo' (<class 'test.test_module.FullLoader'>)>")

    def test_module_repr_with_bare_loader_and_filename(self):
        m = ModuleType('foo')
        # Yes, a class not an instance.
        m.__loader__ = BareLoader
        m.__file__ = '/tmp/foo.py'
        self.assertEqual(repr(m), "<module 'foo' from '/tmp/foo.py'>")

    def test_module_repr_with_full_loader_and_filename(self):
        m = ModuleType('foo')
        # Yes, a class not an instance.
        m.__loader__ = FullLoader
        m.__file__ = '/tmp/foo.py'
        self.assertEqual(repr(m), "<module 'foo' from '/tmp/foo.py'>")

    def test_module_repr_builtin(self):
        self.assertEqual(repr(sys), "<module 'sys' (built-in)>")

    def test_module_repr_source(self):
        r = repr(unittest)
        starts_with = "<module 'unittest' from '"
        ends_with = "__init__.py'>"
        self.assertEqual(r[:len(starts_with)], starts_with,
                         '{!r} does not start with {!r}'.format(r, starts_with))
        self.assertEqual(r[-len(ends_with):], ends_with,
                         '{!r} does not end with {!r}'.format(r, ends_with))

    def test_module_finalization_at_shutdown(self):
        # Module globals and builtins should still be available during shutdown
        rc, out, err = assert_python_ok("-c", "from test import final_a")
        self.assertFalse(err)
        lines = out.splitlines()
        self.assertEqual(set(lines), {
            b"x = a",
            b"x = b",
            b"final_a.x = a",
            b"final_b.x = b",
            b"len = len",
            b"shutil.rmtree = rmtree"})

    def test_descriptor_errors_propagate(self):
        class Descr:
            def __get__(self, o, t):
                raise RuntimeError
        class M(ModuleType):
            melon = Descr()
        self.assertRaises(RuntimeError, getattr, M("mymod"), "melon")

    def test_lazy_create_annotations(self):
        # module objects lazy create their __annotations__ dict on demand.
        # the annotations dict is stored in module.__dict__.
        # a freshly created module shouldn't have an annotations dict yet.
        foo = ModuleType("foo")
        for i in range(4):
            self.assertFalse("__annotations__" in foo.__dict__)
            d = foo.__annotations__
            self.assertTrue("__annotations__" in foo.__dict__)
            self.assertEqual(foo.__annotations__, d)
            self.assertEqual(foo.__dict__['__annotations__'], d)
            if i % 2:
                del foo.__annotations__
            else:
                del foo.__dict__['__annotations__']

    def test_setting_annotations(self):
        foo = ModuleType("foo")
        for i in range(4):
            self.assertFalse("__annotations__" in foo.__dict__)
            d = {'a': int}
            foo.__annotations__ = d
            self.assertTrue("__annotations__" in foo.__dict__)
            self.assertEqual(foo.__annotations__, d)
            self.assertEqual(foo.__dict__['__annotations__'], d)
            if i % 2:
                del foo.__annotations__
            else:
                del foo.__dict__['__annotations__']

    def test_annotations_getset_raises(self):
        # double delete
        foo = ModuleType("foo")
        foo.__annotations__ = {}
        del foo.__annotations__
        with self.assertRaises(AttributeError):
            del foo.__annotations__

    def test_annotations_are_created_correctly(self):
        ann_module4 = import_helper.import_fresh_module('test.ann_module4')
        self.assertTrue("__annotations__" in ann_module4.__dict__)
        del ann_module4.__annotations__
        self.assertFalse("__annotations__" in ann_module4.__dict__)


    def test_repeated_attribute_pops(self):
        # Repeated accesses to module attribute will be specialized
        # Check that popping the attribute doesn't break it
        m = ModuleType("test")
        d = m.__dict__
        count = 0
        for _ in range(100):
            m.attr = 1
            count += m.attr # Might be specialized
            d.pop("attr")
        self.assertEqual(count, 100)

    # frozen and namespace module reprs are tested in importlib.

    def test_subclass_with_slots(self):
        # In 3.11alpha this crashed, as the slots weren't NULLed.

        class ModuleWithSlots(ModuleType):
            __slots__ = ("a", "b")

            def __init__(self, name):
                super().__init__(name)

        m = ModuleWithSlots("name")
        with self.assertRaises(AttributeError):
            m.a
        with self.assertRaises(AttributeError):
            m.b
        m.a, m.b = 1, 2
        self.assertEqual(m.a, 1)
        self.assertEqual(m.b, 2)



if __name__ == '__main__':
    unittest.main()
import os
import errno
import importlib.machinery
import py_compile
import shutil
import unittest
import tempfile

from test import support

import modulefinder

# Each test description is a list of 5 items:
#
# 1. a module name that will be imported by modulefinder
# 2. a list of module names that modulefinder is required to find
# 3. a list of module names that modulefinder should complain
#    about because they are not found
# 4. a list of module names that modulefinder should complain
#    about because they MAY be not found
# 5. a string specifying packages to create; the format is obvious imo.
#
# Each package will be created in test_dir, and test_dir will be
# removed after the tests again.
# Modulefinder searches in a path that contains test_dir, plus
# the standard Lib directory.

maybe_test = [
    "a.module",
    ["a", "a.module", "sys",
     "b"],
    ["c"], ["b.something"],
    """\
a/__init__.py
a/module.py
                                from b import something
                                from c import something
b/__init__.py
                                from sys import *
""",
]

maybe_test_new = [
    "a.module",
    ["a", "a.module", "sys",
     "b", "__future__"],
    ["c"], ["b.something"],
    """\
a/__init__.py
a/module.py
                                from b import something
                                from c import something
b/__init__.py
                                from __future__ import absolute_import
                                from sys import *
"""]

package_test = [
    "a.module",
    ["a", "a.b", "a.c", "a.module", "mymodule", "sys"],
    ["blahblah", "c"], [],
    """\
mymodule.py
a/__init__.py
                                import blahblah
                                from a import b
                                import c
a/module.py
                                import sys
                                from a import b as x
                                from a.c import sillyname
a/b.py
a/c.py
                                from a.module import x
                                import mymodule as sillyname
                                from sys import version_info
"""]

absolute_import_test = [
    "a.module",
    ["a", "a.module",
     "b", "b.x", "b.y", "b.z",
     "__future__", "sys", "gc"],
    ["blahblah", "z"], [],
    """\
mymodule.py
a/__init__.py
a/module.py
                                from __future__ import absolute_import
                                import sys # sys
                                import blahblah # fails
                                import gc # gc
                                import b.x # b.x
                                from b import y # b.y
                                from b.z import * # b.z.*
a/gc.py
a/sys.py
                                import mymodule
a/b/__init__.py
a/b/x.py
a/b/y.py
a/b/z.py
b/__init__.py
                                import z
b/unused.py
b/x.py
b/y.py
b/z.py
"""]

relative_import_test = [
    "a.module",
    ["__future__",
     "a", "a.module",
     "a.b", "a.b.y", "a.b.z",
     "a.b.c", "a.b.c.moduleC",
     "a.b.c.d", "a.b.c.e",
     "a.b.x",
     "gc"],
    [], [],
    """\
mymodule.py
a/__init__.py
                                from .b import y, z # a.b.y, a.b.z
a/module.py
                                from __future__ import absolute_import # __future__
                                import gc # gc
a/gc.py
a/sys.py
a/b/__init__.py
                                from ..b import x # a.b.x
                                #from a.b.c import moduleC
                                from .c import moduleC # a.b.moduleC
a/b/x.py
a/b/y.py
a/b/z.py
a/b/g.py
a/b/c/__init__.py
                                from ..c import e # a.b.c.e
a/b/c/moduleC.py
                                from ..c import d # a.b.c.d
a/b/c/d.py
a/b/c/e.py
a/b/c/x.py
"""]

relative_import_test_2 = [
    "a.module",
    ["a", "a.module",
     "a.sys",
     "a.b", "a.b.y", "a.b.z",
     "a.b.c", "a.b.c.d",
     "a.b.c.e",
     "a.b.c.moduleC",
     "a.b.c.f",
     "a.b.x",
     "a.another"],
    [], [],
    """\
mymodule.py
a/__init__.py
                                from . import sys # a.sys
a/another.py
a/module.py
                                from .b import y, z # a.b.y, a.b.z
a/gc.py
a/sys.py
a/b/__init__.py
                                from .c import moduleC # a.b.c.moduleC
                                from .c import d # a.b.c.d
a/b/x.py
a/b/y.py
a/b/z.py
a/b/c/__init__.py
                                from . import e # a.b.c.e
a/b/c/moduleC.py
                                #
                                from . import f   # a.b.c.f
                                from .. import x  # a.b.x
                                from ... import another # a.another
a/b/c/d.py
a/b/c/e.py
a/b/c/f.py
"""]

relative_import_test_3 = [
    "a.module",
    ["a", "a.module"],
    ["a.bar"],
    [],
    """\
a/__init__.py
                                def foo(): pass
a/module.py
                                from . import foo
                                from . import bar
"""]

relative_import_test_4 = [
    "a.module",
    ["a", "a.module"],
    [],
    [],
    """\
a/__init__.py
                                def foo(): pass
a/module.py
                                from . import *
"""]

bytecode_test = [
    "a",
    ["a"],
    [],
    [],
    ""
]

syntax_error_test = [
    "a.module",
    ["a", "a.module", "b"],
    ["b.module"], [],
    """\
a/__init__.py
a/module.py
                                import b.module
b/__init__.py
b/module.py
                                ?  # SyntaxError: invalid syntax
"""]


same_name_as_bad_test = [
    "a.module",
    ["a", "a.module", "b", "b.c"],
    ["c"], [],
    """\
a/__init__.py
a/module.py
                                import c
                                from b import c
b/__init__.py
b/c.py
"""]

coding_default_utf8_test = [
    "a_utf8",
    ["a_utf8", "b_utf8"],
    [], [],
    """\
a_utf8.py
                                # use the default of utf8
                                print('Unicode test A code point 2090 \u2090 that is not valid in cp1252')
                                import b_utf8
b_utf8.py
                                # use the default of utf8
                                print('Unicode test B code point 2090 \u2090 that is not valid in cp1252')
"""]

coding_explicit_utf8_test = [
    "a_utf8",
    ["a_utf8", "b_utf8"],
    [], [],
    """\
a_utf8.py
                                # coding=utf8
                                print('Unicode test A code point 2090 \u2090 that is not valid in cp1252')
                                import b_utf8
b_utf8.py
                                # use the default of utf8
                                print('Unicode test B code point 2090 \u2090 that is not valid in cp1252')
"""]

coding_explicit_cp1252_test = [
    "a_cp1252",
    ["a_cp1252", "b_utf8"],
    [], [],
    b"""\
a_cp1252.py
                                # coding=cp1252
                                # 0xe2 is not allowed in utf8
                                print('CP1252 test P\xe2t\xe9')
                                import b_utf8
""" + """\
b_utf8.py
                                # use the default of utf8
                                print('Unicode test A code point 2090 \u2090 that is not valid in cp1252')
""".encode('utf-8')]

def open_file(path):
    dirname = os.path.dirname(path)
    try:
        os.makedirs(dirname)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise
    return open(path, 'wb')


def create_package(test_dir, source):
    ofi = None
    try:
        for line in source.splitlines():
            if type(line) != bytes:
                line = line.encode('utf-8')
            if line.startswith(b' ') or line.startswith(b'\t'):
                ofi.write(line.strip() + b'\n')
            else:
                if ofi:
                    ofi.close()
                if type(line) == bytes:
                    line = line.decode('utf-8')
                ofi = open_file(os.path.join(test_dir, line.strip()))
    finally:
        if ofi:
            ofi.close()

class ModuleFinderTest(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.test_path = [self.test_dir, os.path.dirname(tempfile.__file__)]

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def _do_test(self, info, report=False, debug=0, replace_paths=[], modulefinder_class=modulefinder.ModuleFinder):
        import_this, modules, missing, maybe_missing, source = info
        create_package(self.test_dir, source)
        mf = modulefinder_class(path=self.test_path, debug=debug,
                                        replace_paths=replace_paths)
        mf.import_hook(import_this)
        if report:
            mf.report()
##            # This wouldn't work in general when executed several times:
##            opath = sys.path[:]
##            sys.path = self.test_path
##            try:
##                __import__(import_this)
##            except:
##                import traceback; traceback.print_exc()
##            sys.path = opath
##            return
        modules = sorted(set(modules))
        found = sorted(mf.modules)
        # check if we found what we expected, not more, not less
        self.assertEqual(found, modules)

        # check for missing and maybe missing modules
        bad, maybe = mf.any_missing_maybe()
        self.assertEqual(bad, missing)
        self.assertEqual(maybe, maybe_missing)

    def test_package(self):
        self._do_test(package_test)

    def test_maybe(self):
        self._do_test(maybe_test)

    def test_maybe_new(self):
        self._do_test(maybe_test_new)

    def test_absolute_imports(self):
        self._do_test(absolute_import_test)

    def test_relative_imports(self):
        self._do_test(relative_import_test)

    def test_relative_imports_2(self):
        self._do_test(relative_import_test_2)

    def test_relative_imports_3(self):
        self._do_test(relative_import_test_3)

    def test_relative_imports_4(self):
        self._do_test(relative_import_test_4)

    def test_syntax_error(self):
        self._do_test(syntax_error_test)

    def test_same_name_as_bad(self):
        self._do_test(same_name_as_bad_test)

    def test_bytecode(self):
        base_path = os.path.join(self.test_dir, 'a')
        source_path = base_path + importlib.machinery.SOURCE_SUFFIXES[0]
        bytecode_path = base_path + importlib.machinery.BYTECODE_SUFFIXES[0]
        with open_file(source_path) as file:
            file.write('testing_modulefinder = True\n'.encode('utf-8'))
        py_compile.compile(source_path, cfile=bytecode_path)
        os.remove(source_path)
        self._do_test(bytecode_test)

    def test_replace_paths(self):
        old_path = os.path.join(self.test_dir, 'a', 'module.py')
        new_path = os.path.join(self.test_dir, 'a', 'spam.py')
        with support.captured_stdout() as output:
            self._do_test(maybe_test, debug=2,
                          replace_paths=[(old_path, new_path)])
        output = output.getvalue()
        expected = "co_filename %r changed to %r" % (old_path, new_path)
        self.assertIn(expected, output)

    def test_extended_opargs(self):
        extended_opargs_test = [
            "a",
            ["a", "b"],
            [], [],
            """\
a.py
                                %r
                                import b
b.py
""" % list(range(2**16))]  # 2**16 constants
        self._do_test(extended_opargs_test)

    def test_coding_default_utf8(self):
        self._do_test(coding_default_utf8_test)

    def test_coding_explicit_utf8(self):
        self._do_test(coding_explicit_utf8_test)

    def test_coding_explicit_cp1252(self):
        self._do_test(coding_explicit_cp1252_test)

    def test_load_module_api(self):
        class CheckLoadModuleApi(modulefinder.ModuleFinder):
            def __init__(self, *args, **kwds):
                super().__init__(*args, **kwds)

            def load_module(self, fqname, fp, pathname, file_info):
                # confirm that the fileinfo is a tuple of 3 elements
                suffix, mode, type = file_info
                return super().load_module(fqname, fp, pathname, file_info)

        self._do_test(absolute_import_test, modulefinder_class=CheckLoadModuleApi)

if __name__ == "__main__":
    unittest.main()
""" Test suite for the code in msilib """
import os
import unittest
from test.support.import_helper import import_module
from test.support.os_helper import TESTFN, unlink
import warnings
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    msilib = import_module('msilib')
import msilib.schema


def init_database():
    path = TESTFN + '.msi'
    db = msilib.init_database(
        path,
        msilib.schema,
        'Python Tests',
        'product_code',
        '1.0',
        'PSF',
    )
    return db, path


class MsiDatabaseTestCase(unittest.TestCase):

    def test_view_fetch_returns_none(self):
        db, db_path = init_database()
        properties = []
        view = db.OpenView('SELECT Property, Value FROM Property')
        view.Execute(None)
        while True:
            record = view.Fetch()
            if record is None:
                break
            properties.append(record.GetString(1))
        view.Close()
        db.Close()
        self.assertEqual(
            properties,
            [
                'ProductName', 'ProductCode', 'ProductVersion',
                'Manufacturer', 'ProductLanguage',
            ]
        )
        self.addCleanup(unlink, db_path)

    def test_view_non_ascii(self):
        db, db_path = init_database()
        view = db.OpenView("SELECT 'ß-розпад' FROM Property")
        view.Execute(None)
        record = view.Fetch()
        self.assertEqual(record.GetString(1), 'ß-розпад')
        view.Close()
        db.Close()
        self.addCleanup(unlink, db_path)

    def test_summaryinfo_getproperty_issue1104(self):
        db, db_path = init_database()
        try:
            sum_info = db.GetSummaryInformation(99)
            title = sum_info.GetProperty(msilib.PID_TITLE)
            self.assertEqual(title, b"Installation Database")

            sum_info.SetProperty(msilib.PID_TITLE, "a" * 999)
            title = sum_info.GetProperty(msilib.PID_TITLE)
            self.assertEqual(title, b"a" * 999)

            sum_info.SetProperty(msilib.PID_TITLE, "a" * 1000)
            title = sum_info.GetProperty(msilib.PID_TITLE)
            self.assertEqual(title, b"a" * 1000)

            sum_info.SetProperty(msilib.PID_TITLE, "a" * 1001)
            title = sum_info.GetProperty(msilib.PID_TITLE)
            self.assertEqual(title, b"a" * 1001)
        finally:
            db = None
            sum_info = None
            os.unlink(db_path)

    def test_database_open_failed(self):
        with self.assertRaises(msilib.MSIError) as cm:
            msilib.OpenDatabase('non-existent.msi', msilib.MSIDBOPEN_READONLY)
        self.assertEqual(str(cm.exception), 'open failed')

    def test_database_create_failed(self):
        db_path = os.path.join(TESTFN, 'test.msi')
        with self.assertRaises(msilib.MSIError) as cm:
            msilib.OpenDatabase(db_path, msilib.MSIDBOPEN_CREATE)
        self.assertEqual(str(cm.exception), 'create failed')

    def test_get_property_vt_empty(self):
        db, db_path = init_database()
        summary = db.GetSummaryInformation(0)
        self.assertIsNone(summary.GetProperty(msilib.PID_SECURITY))
        db.Close()
        self.addCleanup(unlink, db_path)

    def test_directory_start_component_keyfile(self):
        db, db_path = init_database()
        self.addCleanup(unlink, db_path)
        self.addCleanup(db.Close)
        self.addCleanup(msilib._directories.clear)
        feature = msilib.Feature(db, 0, 'Feature', 'A feature', 'Python')
        cab = msilib.CAB('CAB')
        dir = msilib.Directory(db, cab, None, TESTFN, 'TARGETDIR',
                               'SourceDir', 0)
        dir.start_component(None, feature, None, 'keyfile')

    def test_getproperty_uninitialized_var(self):
        db, db_path = init_database()
        self.addCleanup(unlink, db_path)
        self.addCleanup(db.Close)
        si = db.GetSummaryInformation(0)
        with self.assertRaises(msilib.MSIError):
            si.GetProperty(-1)

    def test_FCICreate(self):
        filepath = TESTFN + '.txt'
        cabpath = TESTFN + '.cab'
        self.addCleanup(unlink, filepath)
        with open(filepath, 'wb'):
            pass
        self.addCleanup(unlink, cabpath)
        msilib.FCICreate(cabpath, [(filepath, 'test.txt')])
        self.assertTrue(os.path.isfile(cabpath))


class Test_make_id(unittest.TestCase):
    #http://msdn.microsoft.com/en-us/library/aa369212(v=vs.85).aspx
    """The Identifier data type is a text string. Identifiers may contain the
    ASCII characters A-Z (a-z), digits, underscores (_), or periods (.).
    However, every identifier must begin with either a letter or an
    underscore.
    """

    def test_is_no_change_required(self):
        self.assertEqual(
            msilib.make_id("short"), "short")
        self.assertEqual(
            msilib.make_id("nochangerequired"), "nochangerequired")
        self.assertEqual(
            msilib.make_id("one.dot"), "one.dot")
        self.assertEqual(
            msilib.make_id("_"), "_")
        self.assertEqual(
            msilib.make_id("a"), "a")
        #self.assertEqual(
        #    msilib.make_id(""), "")

    def test_invalid_first_char(self):
        self.assertEqual(
            msilib.make_id("9.short"), "_9.short")
        self.assertEqual(
            msilib.make_id(".short"), "_.short")

    def test_invalid_any_char(self):
        self.assertEqual(
            msilib.make_id(".s\x82ort"), "_.s_ort")
        self.assertEqual(
            msilib.make_id(".s\x82o?*+rt"), "_.s_o___rt")


if __name__ == '__main__':
    unittest.main()
#
# test_multibytecodec.py
#   Unit test for multibytecodec itself
#

import _multibytecodec
import codecs
import io
import sys
import textwrap
import unittest
from test import support
from test.support import os_helper
from test.support.os_helper import TESTFN

ALL_CJKENCODINGS = [
# _codecs_cn
    'gb2312', 'gbk', 'gb18030', 'hz',
# _codecs_hk
    'big5hkscs',
# _codecs_jp
    'cp932', 'shift_jis', 'euc_jp', 'euc_jisx0213', 'shift_jisx0213',
    'euc_jis_2004', 'shift_jis_2004',
# _codecs_kr
    'cp949', 'euc_kr', 'johab',
# _codecs_tw
    'big5', 'cp950',
# _codecs_iso2022
    'iso2022_jp', 'iso2022_jp_1', 'iso2022_jp_2', 'iso2022_jp_2004',
    'iso2022_jp_3', 'iso2022_jp_ext', 'iso2022_kr',
]

class Test_MultibyteCodec(unittest.TestCase):

    def test_nullcoding(self):
        for enc in ALL_CJKENCODINGS:
            self.assertEqual(b''.decode(enc), '')
            self.assertEqual(str(b'', enc), '')
            self.assertEqual(''.encode(enc), b'')

    def test_str_decode(self):
        for enc in ALL_CJKENCODINGS:
            self.assertEqual('abcd'.encode(enc), b'abcd')

    def test_errorcallback_longindex(self):
        dec = codecs.getdecoder('euc-kr')
        myreplace  = lambda exc: ('', sys.maxsize+1)
        codecs.register_error('test.cjktest', myreplace)
        self.assertRaises(IndexError, dec,
                          b'apple\x92ham\x93spam', 'test.cjktest')

    def test_errorcallback_custom_ignore(self):
        # Issue #23215: MemoryError with custom error handlers and multibyte codecs
        data = 100 * "\udc00"
        codecs.register_error("test.ignore", codecs.ignore_errors)
        for enc in ALL_CJKENCODINGS:
            self.assertEqual(data.encode(enc, "test.ignore"), b'')

    def test_codingspec(self):
        try:
            for enc in ALL_CJKENCODINGS:
                code = '# coding: {}\n'.format(enc)
                exec(code)
        finally:
            os_helper.unlink(TESTFN)

    def test_init_segfault(self):
        # bug #3305: this used to segfault
        self.assertRaises(AttributeError,
                          _multibytecodec.MultibyteStreamReader, None)
        self.assertRaises(AttributeError,
                          _multibytecodec.MultibyteStreamWriter, None)

    def test_decode_unicode(self):
        # Trying to decode a unicode string should raise a TypeError
        for enc in ALL_CJKENCODINGS:
            self.assertRaises(TypeError, codecs.getdecoder(enc), "")

class Test_IncrementalEncoder(unittest.TestCase):

    def test_stateless(self):
        # cp949 encoder isn't stateful at all.
        encoder = codecs.getincrementalencoder('cp949')()
        self.assertEqual(encoder.encode('\ud30c\uc774\uc36c \ub9c8\uc744'),
                         b'\xc6\xc4\xc0\xcc\xbd\xe3 \xb8\xb6\xc0\xbb')
        self.assertEqual(encoder.reset(), None)
        self.assertEqual(encoder.encode('\u2606\u223c\u2606', True),
                         b'\xa1\xd9\xa1\xad\xa1\xd9')
        self.assertEqual(encoder.reset(), None)
        self.assertEqual(encoder.encode('', True), b'')
        self.assertEqual(encoder.encode('', False), b'')
        self.assertEqual(encoder.reset(), None)

    def test_stateful(self):
        # jisx0213 encoder is stateful for a few code points. eg)
        #   U+00E6 => A9DC
        #   U+00E6 U+0300 => ABC4
        #   U+0300 => ABDC

        encoder = codecs.getincrementalencoder('jisx0213')()
        self.assertEqual(encoder.encode('\u00e6\u0300'), b'\xab\xc4')
        self.assertEqual(encoder.encode('\u00e6'), b'')
        self.assertEqual(encoder.encode('\u0300'), b'\xab\xc4')
        self.assertEqual(encoder.encode('\u00e6', True), b'\xa9\xdc')

        self.assertEqual(encoder.reset(), None)
        self.assertEqual(encoder.encode('\u0300'), b'\xab\xdc')

        self.assertEqual(encoder.encode('\u00e6'), b'')
        self.assertEqual(encoder.encode('', True), b'\xa9\xdc')
        self.assertEqual(encoder.encode('', True), b'')

    def test_stateful_keep_buffer(self):
        encoder = codecs.getincrementalencoder('jisx0213')()
        self.assertEqual(encoder.encode('\u00e6'), b'')
        self.assertRaises(UnicodeEncodeError, encoder.encode, '\u0123')
        self.assertEqual(encoder.encode('\u0300\u00e6'), b'\xab\xc4')
        self.assertRaises(UnicodeEncodeError, encoder.encode, '\u0123')
        self.assertEqual(encoder.reset(), None)
        self.assertEqual(encoder.encode('\u0300'), b'\xab\xdc')
        self.assertEqual(encoder.encode('\u00e6'), b'')
        self.assertRaises(UnicodeEncodeError, encoder.encode, '\u0123')
        self.assertEqual(encoder.encode('', True), b'\xa9\xdc')

    def test_state_methods_with_buffer_state(self):
        # euc_jis_2004 stores state as a buffer of pending bytes
        encoder = codecs.getincrementalencoder('euc_jis_2004')()

        initial_state = encoder.getstate()
        self.assertEqual(encoder.encode('\u00e6\u0300'), b'\xab\xc4')
        encoder.setstate(initial_state)
        self.assertEqual(encoder.encode('\u00e6\u0300'), b'\xab\xc4')

        self.assertEqual(encoder.encode('\u00e6'), b'')
        partial_state = encoder.getstate()
        self.assertEqual(encoder.encode('\u0300'), b'\xab\xc4')
        encoder.setstate(partial_state)
        self.assertEqual(encoder.encode('\u0300'), b'\xab\xc4')

    def test_state_methods_with_non_buffer_state(self):
        # iso2022_jp stores state without using a buffer
        encoder = codecs.getincrementalencoder('iso2022_jp')()

        self.assertEqual(encoder.encode('z'), b'z')
        en_state = encoder.getstate()

        self.assertEqual(encoder.encode('\u3042'), b'\x1b\x24\x42\x24\x22')
        jp_state = encoder.getstate()
        self.assertEqual(encoder.encode('z'), b'\x1b\x28\x42z')

        encoder.setstate(jp_state)
        self.assertEqual(encoder.encode('\u3042'), b'\x24\x22')

        encoder.setstate(en_state)
        self.assertEqual(encoder.encode('z'), b'z')

    def test_getstate_returns_expected_value(self):
        # Note: getstate is implemented such that these state values
        # are expected to be the same across all builds of Python,
        # regardless of x32/64 bit, endianness and compiler.

        # euc_jis_2004 stores state as a buffer of pending bytes
        buffer_state_encoder = codecs.getincrementalencoder('euc_jis_2004')()
        self.assertEqual(buffer_state_encoder.getstate(), 0)
        buffer_state_encoder.encode('\u00e6')
        self.assertEqual(buffer_state_encoder.getstate(),
                         int.from_bytes(
                             b"\x02"
                             b"\xc3\xa6"
                             b"\x00\x00\x00\x00\x00\x00\x00\x00",
                             'little'))
        buffer_state_encoder.encode('\u0300')
        self.assertEqual(buffer_state_encoder.getstate(), 0)

        # iso2022_jp stores state without using a buffer
        non_buffer_state_encoder = codecs.getincrementalencoder('iso2022_jp')()
        self.assertEqual(non_buffer_state_encoder.getstate(),
                         int.from_bytes(
                             b"\x00"
                             b"\x42\x42\x00\x00\x00\x00\x00\x00",
                             'little'))
        non_buffer_state_encoder.encode('\u3042')
        self.assertEqual(non_buffer_state_encoder.getstate(),
                         int.from_bytes(
                             b"\x00"
                             b"\xc2\x42\x00\x00\x00\x00\x00\x00",
                             'little'))

    def test_setstate_validates_input_size(self):
        encoder = codecs.getincrementalencoder('euc_jp')()
        pending_size_nine = int.from_bytes(
            b"\x09"
            b"\x00\x00\x00\x00\x00\x00\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00",
            'little')
        self.assertRaises(UnicodeError, encoder.setstate, pending_size_nine)

    def test_setstate_validates_input_bytes(self):
        encoder = codecs.getincrementalencoder('euc_jp')()
        invalid_utf8 = int.from_bytes(
            b"\x01"
            b"\xff"
            b"\x00\x00\x00\x00\x00\x00\x00\x00",
            'little')
        self.assertRaises(UnicodeDecodeError, encoder.setstate, invalid_utf8)

    def test_issue5640(self):
        encoder = codecs.getincrementalencoder('shift-jis')('backslashreplace')
        self.assertEqual(encoder.encode('\xff'), b'\\xff')
        self.assertEqual(encoder.encode('\n'), b'\n')

    @support.cpython_only
    def test_subinterp(self):
        # bpo-42846: Test a CJK codec in a subinterpreter
        import _testcapi
        encoding = 'cp932'
        text = "Python の開発は、1990 年ごろから開始されています。"
        code = textwrap.dedent("""
            import codecs
            encoding = %r
            text = %r
            encoder = codecs.getincrementalencoder(encoding)()
            text2 = encoder.encode(text).decode(encoding)
            if text2 != text:
                raise ValueError(f"encoding issue: {text2!a} != {text!a}")
        """) % (encoding, text)
        res = _testcapi.run_in_subinterp(code)
        self.assertEqual(res, 0)

class Test_IncrementalDecoder(unittest.TestCase):

    def test_dbcs(self):
        # cp949 decoder is simple with only 1 or 2 bytes sequences.
        decoder = codecs.getincrementaldecoder('cp949')()
        self.assertEqual(decoder.decode(b'\xc6\xc4\xc0\xcc\xbd'),
                         '\ud30c\uc774')
        self.assertEqual(decoder.decode(b'\xe3 \xb8\xb6\xc0\xbb'),
                         '\uc36c \ub9c8\uc744')
        self.assertEqual(decoder.decode(b''), '')

    def test_dbcs_keep_buffer(self):
        decoder = codecs.getincrementaldecoder('cp949')()
        self.assertEqual(decoder.decode(b'\xc6\xc4\xc0'), '\ud30c')
        self.assertRaises(UnicodeDecodeError, decoder.decode, b'', True)
        self.assertEqual(decoder.decode(b'\xcc'), '\uc774')

        self.assertEqual(decoder.decode(b'\xc6\xc4\xc0'), '\ud30c')
        self.assertRaises(UnicodeDecodeError, decoder.decode,
                          b'\xcc\xbd', True)
        self.assertEqual(decoder.decode(b'\xcc'), '\uc774')

    def test_iso2022(self):
        decoder = codecs.getincrementaldecoder('iso2022-jp')()
        ESC = b'\x1b'
        self.assertEqual(decoder.decode(ESC + b'('), '')
        self.assertEqual(decoder.decode(b'B', True), '')
        self.assertEqual(decoder.decode(ESC + b'$'), '')
        self.assertEqual(decoder.decode(b'B@$'), '\u4e16')
        self.assertEqual(decoder.decode(b'@$@'), '\u4e16')
        self.assertEqual(decoder.decode(b'$', True), '\u4e16')
        self.assertEqual(decoder.reset(), None)
        self.assertEqual(decoder.decode(b'@$'), '@$')
        self.assertEqual(decoder.decode(ESC + b'$'), '')
        self.assertRaises(UnicodeDecodeError, decoder.decode, b'', True)
        self.assertEqual(decoder.decode(b'B@$'), '\u4e16')

    def test_decode_unicode(self):
        # Trying to decode a unicode string should raise a TypeError
        for enc in ALL_CJKENCODINGS:
            decoder = codecs.getincrementaldecoder(enc)()
            self.assertRaises(TypeError, decoder.decode, "")

    def test_state_methods(self):
        decoder = codecs.getincrementaldecoder('euc_jp')()

        # Decode a complete input sequence
        self.assertEqual(decoder.decode(b'\xa4\xa6'), '\u3046')
        pending1, _ = decoder.getstate()
        self.assertEqual(pending1, b'')

        # Decode first half of a partial input sequence
        self.assertEqual(decoder.decode(b'\xa4'), '')
        pending2, flags2 = decoder.getstate()
        self.assertEqual(pending2, b'\xa4')

        # Decode second half of a partial input sequence
        self.assertEqual(decoder.decode(b'\xa6'), '\u3046')
        pending3, _ = decoder.getstate()
        self.assertEqual(pending3, b'')

        # Jump back and decode second half of partial input sequence again
        decoder.setstate((pending2, flags2))
        self.assertEqual(decoder.decode(b'\xa6'), '\u3046')
        pending4, _ = decoder.getstate()
        self.assertEqual(pending4, b'')

        # Ensure state values are preserved correctly
        decoder.setstate((b'abc', 123456789))
        self.assertEqual(decoder.getstate(), (b'abc', 123456789))

    def test_setstate_validates_input(self):
        decoder = codecs.getincrementaldecoder('euc_jp')()
        self.assertRaises(TypeError, decoder.setstate, 123)
        self.assertRaises(TypeError, decoder.setstate, ("invalid", 0))
        self.assertRaises(TypeError, decoder.setstate, (b"1234", "invalid"))
        self.assertRaises(UnicodeError, decoder.setstate, (b"123456789", 0))

class Test_StreamReader(unittest.TestCase):
    def test_bug1728403(self):
        try:
            f = open(TESTFN, 'wb')
            try:
                f.write(b'\xa1')
            finally:
                f.close()
            f = codecs.open(TESTFN, encoding='cp949')
            try:
                self.assertRaises(UnicodeDecodeError, f.read, 2)
            finally:
                f.close()
        finally:
            os_helper.unlink(TESTFN)

class Test_StreamWriter(unittest.TestCase):
    def test_gb18030(self):
        s= io.BytesIO()
        c = codecs.getwriter('gb18030')(s)
        c.write('123')
        self.assertEqual(s.getvalue(), b'123')
        c.write('\U00012345')
        self.assertEqual(s.getvalue(), b'123\x907\x959')
        c.write('\uac00\u00ac')
        self.assertEqual(s.getvalue(),
                b'123\x907\x959\x827\xcf5\x810\x851')

    def test_utf_8(self):
        s= io.BytesIO()
        c = codecs.getwriter('utf-8')(s)
        c.write('123')
        self.assertEqual(s.getvalue(), b'123')
        c.write('\U00012345')
        self.assertEqual(s.getvalue(), b'123\xf0\x92\x8d\x85')
        c.write('\uac00\u00ac')
        self.assertEqual(s.getvalue(),
            b'123\xf0\x92\x8d\x85'
            b'\xea\xb0\x80\xc2\xac')

    def test_streamwriter_strwrite(self):
        s = io.BytesIO()
        wr = codecs.getwriter('gb18030')(s)
        wr.write('abcd')
        self.assertEqual(s.getvalue(), b'abcd')

class Test_ISO2022(unittest.TestCase):
    def test_g2(self):
        iso2022jp2 = b'\x1b(B:hu4:unit\x1b.A\x1bNi de famille'
        uni = ':hu4:unit\xe9 de famille'
        self.assertEqual(iso2022jp2.decode('iso2022-jp-2'), uni)

    def test_iso2022_jp_g0(self):
        self.assertNotIn(b'\x0e', '\N{SOFT HYPHEN}'.encode('iso-2022-jp-2'))
        for encoding in ('iso-2022-jp-2004', 'iso-2022-jp-3'):
            e = '\u3406'.encode(encoding)
            self.assertFalse(any(x > 0x80 for x in e))

    def test_bug1572832(self):
        for x in range(0x10000, 0x110000):
            # Any ISO 2022 codec will cause the segfault
            chr(x).encode('iso_2022_jp', 'ignore')

class TestStateful(unittest.TestCase):
    text = '\u4E16\u4E16'
    encoding = 'iso-2022-jp'
    expected = b'\x1b$B@$@$'
    reset = b'\x1b(B'
    expected_reset = expected + reset

    def test_encode(self):
        self.assertEqual(self.text.encode(self.encoding), self.expected_reset)

    def test_incrementalencoder(self):
        encoder = codecs.getincrementalencoder(self.encoding)()
        output = b''.join(
            encoder.encode(char)
            for char in self.text)
        self.assertEqual(output, self.expected)
        self.assertEqual(encoder.encode('', final=True), self.reset)
        self.assertEqual(encoder.encode('', final=True), b'')

    def test_incrementalencoder_final(self):
        encoder = codecs.getincrementalencoder(self.encoding)()
        last_index = len(self.text) - 1
        output = b''.join(
            encoder.encode(char, index == last_index)
            for index, char in enumerate(self.text))
        self.assertEqual(output, self.expected_reset)
        self.assertEqual(encoder.encode('', final=True), b'')

class TestHZStateful(TestStateful):
    text = '\u804a\u804a'
    encoding = 'hz'
    expected = b'~{ADAD'
    reset = b'~}'
    expected_reset = expected + reset


if __name__ == "__main__":
    unittest.main()
import unittest
import test._test_multiprocessing

import sys
from test import support

if support.PGO:
    raise unittest.SkipTest("test is not helpful for PGO")

if sys.platform == "win32":
    raise unittest.SkipTest("fork is not available on Windows")

if sys.platform == 'darwin':
    raise unittest.SkipTest("test may crash on macOS (bpo-33725)")

test._test_multiprocessing.install_tests_in_module_dict(globals(), 'fork')

if __name__ == '__main__':
    unittest.main()
import unittest
import test._test_multiprocessing

import sys
from test import support

if support.PGO:
    raise unittest.SkipTest("test is not helpful for PGO")

if sys.platform == "win32":
    raise unittest.SkipTest("forkserver is not available on Windows")

test._test_multiprocessing.install_tests_in_module_dict(globals(), 'forkserver')

if __name__ == '__main__':
    unittest.main()
# tests __main__ module handling in multiprocessing
from test import support
from test.support import import_helper
# Skip tests if _multiprocessing wasn't built.
import_helper.import_module('_multiprocessing')

import importlib
import importlib.machinery
import unittest
import sys
import os
import os.path
import py_compile

from test.support import os_helper
from test.support.script_helper import (
    make_pkg, make_script, make_zip_pkg, make_zip_script,
    assert_python_ok)

if support.PGO:
    raise unittest.SkipTest("test is not helpful for PGO")

# Look up which start methods are available to test
import multiprocessing
AVAILABLE_START_METHODS = set(multiprocessing.get_all_start_methods())

# Issue #22332: Skip tests if sem_open implementation is broken.
support.skip_if_broken_multiprocessing_synchronize()

verbose = support.verbose

test_source = """\
# multiprocessing includes all sorts of shenanigans to make __main__
# attributes accessible in the subprocess in a pickle compatible way.

# We run the "doesn't work in the interactive interpreter" example from
# the docs to make sure it *does* work from an executed __main__,
# regardless of the invocation mechanism

import sys
import time
from multiprocessing import Pool, set_start_method
from test import support

# We use this __main__ defined function in the map call below in order to
# check that multiprocessing in correctly running the unguarded
# code in child processes and then making it available as __main__
def f(x):
    return x*x

# Check explicit relative imports
if "check_sibling" in __file__:
    # We're inside a package and not in a __main__.py file
    # so make sure explicit relative imports work correctly
    from . import sibling

if __name__ == '__main__':
    start_method = sys.argv[1]
    set_start_method(start_method)
    results = []
    with Pool(5) as pool:
        pool.map_async(f, [1, 2, 3], callback=results.extend)

        # up to 1 min to report the results
        for _ in support.sleeping_retry(support.LONG_TIMEOUT,
                                        "Timed out waiting for results"):
            if results:
                break

    results.sort()
    print(start_method, "->", results)

    pool.join()
"""

test_source_main_skipped_in_children = """\
# __main__.py files have an implied "if __name__ == '__main__'" so
# multiprocessing should always skip running them in child processes

# This means we can't use __main__ defined functions in child processes,
# so we just use "int" as a passthrough operation below

if __name__ != "__main__":
    raise RuntimeError("Should only be called as __main__!")

import sys
import time
from multiprocessing import Pool, set_start_method
from test import support

start_method = sys.argv[1]
set_start_method(start_method)
results = []
with Pool(5) as pool:
    pool.map_async(int, [1, 4, 9], callback=results.extend)
    # up to 1 min to report the results
    for _ in support.sleeping_retry(support.LONG_TIMEOUT,
                                    "Timed out waiting for results"):
        if results:
            break

results.sort()
print(start_method, "->", results)

pool.join()
"""

# These helpers were copied from test_cmd_line_script & tweaked a bit...

def _make_test_script(script_dir, script_basename,
                      source=test_source, omit_suffix=False):
    to_return = make_script(script_dir, script_basename,
                            source, omit_suffix)
    # Hack to check explicit relative imports
    if script_basename == "check_sibling":
        make_script(script_dir, "sibling", "")
    importlib.invalidate_caches()
    return to_return

def _make_test_zip_pkg(zip_dir, zip_basename, pkg_name, script_basename,
                       source=test_source, depth=1):
    to_return = make_zip_pkg(zip_dir, zip_basename, pkg_name, script_basename,
                             source, depth)
    importlib.invalidate_caches()
    return to_return

# There's no easy way to pass the script directory in to get
# -m to work (avoiding that is the whole point of making
# directories and zipfiles executable!)
# So we fake it for testing purposes with a custom launch script
launch_source = """\
import sys, os.path, runpy
sys.path.insert(0, %s)
runpy._run_module_as_main(%r)
"""

def _make_launch_script(script_dir, script_basename, module_name, path=None):
    if path is None:
        path = "os.path.dirname(__file__)"
    else:
        path = repr(path)
    source = launch_source % (path, module_name)
    to_return = make_script(script_dir, script_basename, source)
    importlib.invalidate_caches()
    return to_return

class MultiProcessingCmdLineMixin():
    maxDiff = None # Show full tracebacks on subprocess failure

    def setUp(self):
        if self.start_method not in AVAILABLE_START_METHODS:
            self.skipTest("%r start method not available" % self.start_method)

    def _check_output(self, script_name, exit_code, out, err):
        if verbose > 1:
            print("Output from test script %r:" % script_name)
            print(repr(out))
        self.assertEqual(exit_code, 0)
        self.assertEqual(err.decode('utf-8'), '')
        expected_results = "%s -> [1, 4, 9]" % self.start_method
        self.assertEqual(out.decode('utf-8').strip(), expected_results)

    def _check_script(self, script_name, *cmd_line_switches):
        if not __debug__:
            cmd_line_switches += ('-' + 'O' * sys.flags.optimize,)
        run_args = cmd_line_switches + (script_name, self.start_method)
        rc, out, err = assert_python_ok(*run_args, __isolated=False)
        self._check_output(script_name, rc, out, err)

    def test_basic_script(self):
        with os_helper.temp_dir() as script_dir:
            script_name = _make_test_script(script_dir, 'script')
            self._check_script(script_name)

    def test_basic_script_no_suffix(self):
        with os_helper.temp_dir() as script_dir:
            script_name = _make_test_script(script_dir, 'script',
                                            omit_suffix=True)
            self._check_script(script_name)

    def test_ipython_workaround(self):
        # Some versions of the IPython launch script are missing the
        # __name__ = "__main__" guard, and multiprocessing has long had
        # a workaround for that case
        # See https://github.com/ipython/ipython/issues/4698
        source = test_source_main_skipped_in_children
        with os_helper.temp_dir() as script_dir:
            script_name = _make_test_script(script_dir, 'ipython',
                                            source=source)
            self._check_script(script_name)
            script_no_suffix = _make_test_script(script_dir, 'ipython',
                                                 source=source,
                                                 omit_suffix=True)
            self._check_script(script_no_suffix)

    def test_script_compiled(self):
        with os_helper.temp_dir() as script_dir:
            script_name = _make_test_script(script_dir, 'script')
            py_compile.compile(script_name, doraise=True)
            os.remove(script_name)
            pyc_file = import_helper.make_legacy_pyc(script_name)
            self._check_script(pyc_file)

    def test_directory(self):
        source = self.main_in_children_source
        with os_helper.temp_dir() as script_dir:
            script_name = _make_test_script(script_dir, '__main__',
                                            source=source)
            self._check_script(script_dir)

    def test_directory_compiled(self):
        source = self.main_in_children_source
        with os_helper.temp_dir() as script_dir:
            script_name = _make_test_script(script_dir, '__main__',
                                            source=source)
            py_compile.compile(script_name, doraise=True)
            os.remove(script_name)
            pyc_file = import_helper.make_legacy_pyc(script_name)
            self._check_script(script_dir)

    def test_zipfile(self):
        source = self.main_in_children_source
        with os_helper.temp_dir() as script_dir:
            script_name = _make_test_script(script_dir, '__main__',
                                            source=source)
            zip_name, run_name = make_zip_script(script_dir, 'test_zip', script_name)
            self._check_script(zip_name)

    def test_zipfile_compiled(self):
        source = self.main_in_children_source
        with os_helper.temp_dir() as script_dir:
            script_name = _make_test_script(script_dir, '__main__',
                                            source=source)
            compiled_name = py_compile.compile(script_name, doraise=True)
            zip_name, run_name = make_zip_script(script_dir, 'test_zip', compiled_name)
            self._check_script(zip_name)

    def test_module_in_package(self):
        with os_helper.temp_dir() as script_dir:
            pkg_dir = os.path.join(script_dir, 'test_pkg')
            make_pkg(pkg_dir)
            script_name = _make_test_script(pkg_dir, 'check_sibling')
            launch_name = _make_launch_script(script_dir, 'launch',
                                              'test_pkg.check_sibling')
            self._check_script(launch_name)

    def test_module_in_package_in_zipfile(self):
        with os_helper.temp_dir() as script_dir:
            zip_name, run_name = _make_test_zip_pkg(script_dir, 'test_zip', 'test_pkg', 'script')
            launch_name = _make_launch_script(script_dir, 'launch', 'test_pkg.script', zip_name)
            self._check_script(launch_name)

    def test_module_in_subpackage_in_zipfile(self):
        with os_helper.temp_dir() as script_dir:
            zip_name, run_name = _make_test_zip_pkg(script_dir, 'test_zip', 'test_pkg', 'script', depth=2)
            launch_name = _make_launch_script(script_dir, 'launch', 'test_pkg.test_pkg.script', zip_name)
            self._check_script(launch_name)

    def test_package(self):
        source = self.main_in_children_source
        with os_helper.temp_dir() as script_dir:
            pkg_dir = os.path.join(script_dir, 'test_pkg')
            make_pkg(pkg_dir)
            script_name = _make_test_script(pkg_dir, '__main__',
                                            source=source)
            launch_name = _make_launch_script(script_dir, 'launch', 'test_pkg')
            self._check_script(launch_name)

    def test_package_compiled(self):
        source = self.main_in_children_source
        with os_helper.temp_dir() as script_dir:
            pkg_dir = os.path.join(script_dir, 'test_pkg')
            make_pkg(pkg_dir)
            script_name = _make_test_script(pkg_dir, '__main__',
                                            source=source)
            compiled_name = py_compile.compile(script_name, doraise=True)
            os.remove(script_name)
            pyc_file = import_helper.make_legacy_pyc(script_name)
            launch_name = _make_launch_script(script_dir, 'launch', 'test_pkg')
            self._check_script(launch_name)

# Test all supported start methods (setupClass skips as appropriate)

class SpawnCmdLineTest(MultiProcessingCmdLineMixin, unittest.TestCase):
    start_method = 'spawn'
    main_in_children_source = test_source_main_skipped_in_children

class ForkCmdLineTest(MultiProcessingCmdLineMixin, unittest.TestCase):
    start_method = 'fork'
    main_in_children_source = test_source

class ForkServerCmdLineTest(MultiProcessingCmdLineMixin, unittest.TestCase):
    start_method = 'forkserver'
    main_in_children_source = test_source_main_skipped_in_children

def tearDownModule():
    support.reap_children()

if __name__ == '__main__':
    unittest.main()
import unittest
import test._test_multiprocessing

from test import support

if support.PGO:
    raise unittest.SkipTest("test is not helpful for PGO")

test._test_multiprocessing.install_tests_in_module_dict(globals(), 'spawn')

if __name__ == '__main__':
    unittest.main()
import unittest

GLOBAL_VAR = None

class NamedExpressionInvalidTest(unittest.TestCase):

    def test_named_expression_invalid_01(self):
        code = """x := 0"""

        with self.assertRaisesRegex(SyntaxError, "invalid syntax"):
            exec(code, {}, {})

    def test_named_expression_invalid_02(self):
        code = """x = y := 0"""

        with self.assertRaisesRegex(SyntaxError, "invalid syntax"):
            exec(code, {}, {})

    def test_named_expression_invalid_03(self):
        code = """y := f(x)"""

        with self.assertRaisesRegex(SyntaxError, "invalid syntax"):
            exec(code, {}, {})

    def test_named_expression_invalid_04(self):
        code = """y0 = y1 := f(x)"""

        with self.assertRaisesRegex(SyntaxError, "invalid syntax"):
            exec(code, {}, {})

    def test_named_expression_invalid_06(self):
        code = """((a, b) := (1, 2))"""

        with self.assertRaisesRegex(SyntaxError, "cannot use assignment expressions with tuple"):
            exec(code, {}, {})

    def test_named_expression_invalid_07(self):
        code = """def spam(a = b := 42): pass"""

        with self.assertRaisesRegex(SyntaxError, "invalid syntax"):
            exec(code, {}, {})

    def test_named_expression_invalid_08(self):
        code = """def spam(a: b := 42 = 5): pass"""

        with self.assertRaisesRegex(SyntaxError, "invalid syntax"):
            exec(code, {}, {})

    def test_named_expression_invalid_09(self):
        code = """spam(a=b := 'c')"""

        with self.assertRaisesRegex(SyntaxError, "invalid syntax"):
            exec(code, {}, {})

    def test_named_expression_invalid_10(self):
        code = """spam(x = y := f(x))"""

        with self.assertRaisesRegex(SyntaxError, "invalid syntax"):
            exec(code, {}, {})

    def test_named_expression_invalid_11(self):
        code = """spam(a=1, b := 2)"""

        with self.assertRaisesRegex(SyntaxError,
            "positional argument follows keyword argument"):
            exec(code, {}, {})

    def test_named_expression_invalid_12(self):
        code = """spam(a=1, (b := 2))"""

        with self.assertRaisesRegex(SyntaxError,
            "positional argument follows keyword argument"):
            exec(code, {}, {})

    def test_named_expression_invalid_13(self):
        code = """spam(a=1, (b := 2))"""

        with self.assertRaisesRegex(SyntaxError,
            "positional argument follows keyword argument"):
            exec(code, {}, {})

    def test_named_expression_invalid_14(self):
        code = """(x := lambda: y := 1)"""

        with self.assertRaisesRegex(SyntaxError, "invalid syntax"):
            exec(code, {}, {})

    def test_named_expression_invalid_15(self):
        code = """(lambda: x := 1)"""

        with self.assertRaisesRegex(SyntaxError,
            "cannot use assignment expressions with lambda"):
            exec(code, {}, {})

    def test_named_expression_invalid_16(self):
        code = "[i + 1 for i in i := [1,2]]"

        with self.assertRaisesRegex(SyntaxError, "invalid syntax"):
            exec(code, {}, {})

    def test_named_expression_invalid_17(self):
        code = "[i := 0, j := 1 for i, j in [(1, 2), (3, 4)]]"

        with self.assertRaisesRegex(SyntaxError,
                "did you forget parentheses around the comprehension target?"):
            exec(code, {}, {})

    def test_named_expression_invalid_in_class_body(self):
        code = """class Foo():
            [(42, 1 + ((( j := i )))) for i in range(5)]
        """

        with self.assertRaisesRegex(SyntaxError,
            "assignment expression within a comprehension cannot be used in a class body"):
            exec(code, {}, {})

    def test_named_expression_valid_rebinding_iteration_variable(self):
        # This test covers that we can reassign variables
        # that are not directly assigned in the
        # iterable part of a comprehension.
        cases = [
            # Regression tests from https://github.com/python/cpython/issues/87447
            ("Complex expression: c",
                "{0}(c := 1) for a, (*b, c[d+e::f(g)], h.i) in j{1}"),
            ("Complex expression: d",
                "{0}(d := 1) for a, (*b, c[d+e::f(g)], h.i) in j{1}"),
            ("Complex expression: e",
                "{0}(e := 1) for a, (*b, c[d+e::f(g)], h.i) in j{1}"),
            ("Complex expression: f",
                "{0}(f := 1) for a, (*b, c[d+e::f(g)], h.i) in j{1}"),
            ("Complex expression: g",
                "{0}(g := 1) for a, (*b, c[d+e::f(g)], h.i) in j{1}"),
            ("Complex expression: h",
                "{0}(h := 1) for a, (*b, c[d+e::f(g)], h.i) in j{1}"),
            ("Complex expression: i",
                "{0}(i := 1) for a, (*b, c[d+e::f(g)], h.i) in j{1}"),
            ("Complex expression: j",
                "{0}(j := 1) for a, (*b, c[d+e::f(g)], h.i) in j{1}"),
        ]
        for test_case, code in cases:
            for lpar, rpar in [('(', ')'), ('[', ']'), ('{', '}')]:
                code = code.format(lpar, rpar)
                with self.subTest(case=test_case, lpar=lpar, rpar=rpar):
                    # Names used in snippets are not defined,
                    # but we are fine with it: just must not be a SyntaxError.
                    # Names used in snippets are not defined,
                    # but we are fine with it: just must not be a SyntaxError.
                    with self.assertRaises(NameError):
                        exec(code, {}) # Module scope
                    with self.assertRaises(NameError):
                        exec(code, {}, {}) # Class scope
                    exec(f"lambda: {code}", {}) # Function scope

    def test_named_expression_invalid_rebinding_iteration_variable(self):
        # This test covers that we cannot reassign variables
        # that are directly assigned in the iterable part of a comprehension.
        cases = [
            # Regression tests from https://github.com/python/cpython/issues/87447
            ("Complex expression: a", "a",
                "{0}(a := 1) for a, (*b, c[d+e::f(g)], h.i) in j{1}"),
            ("Complex expression: b", "b",
                "{0}(b := 1) for a, (*b, c[d+e::f(g)], h.i) in j{1}"),
        ]
        for test_case, target, code in cases:
            msg = f"assignment expression cannot rebind comprehension iteration variable '{target}'"
            for lpar, rpar in [('(', ')'), ('[', ']'), ('{', '}')]:
                code = code.format(lpar, rpar)
                with self.subTest(case=test_case, lpar=lpar, rpar=rpar):
                    # Names used in snippets are not defined,
                    # but we are fine with it: just must not be a SyntaxError.
                    # Names used in snippets are not defined,
                    # but we are fine with it: just must not be a SyntaxError.
                    with self.assertRaisesRegex(SyntaxError, msg):
                        exec(code, {}) # Module scope
                    with self.assertRaisesRegex(SyntaxError, msg):
                        exec(code, {}, {}) # Class scope
                    with self.assertRaisesRegex(SyntaxError, msg):
                        exec(f"lambda: {code}", {}) # Function scope

    def test_named_expression_invalid_rebinding_list_comprehension_iteration_variable(self):
        cases = [
            ("Local reuse", 'i', "[i := 0 for i in range(5)]"),
            ("Nested reuse", 'j', "[[(j := 0) for i in range(5)] for j in range(5)]"),
            ("Reuse inner loop target", 'j', "[(j := 0) for i in range(5) for j in range(5)]"),
            ("Unpacking reuse", 'i', "[i := 0 for i, j in [(0, 1)]]"),
            ("Reuse in loop condition", 'i', "[i+1 for i in range(5) if (i := 0)]"),
            ("Unreachable reuse", 'i', "[False or (i:=0) for i in range(5)]"),
            ("Unreachable nested reuse", 'i',
                "[(i, j) for i in range(5) for j in range(5) if True or (i:=10)]"),
        ]
        for case, target, code in cases:
            msg = f"assignment expression cannot rebind comprehension iteration variable '{target}'"
            with self.subTest(case=case):
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(code, {}) # Module scope
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(code, {}, {}) # Class scope
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(f"lambda: {code}", {}) # Function scope

    def test_named_expression_invalid_rebinding_list_comprehension_inner_loop(self):
        cases = [
            ("Inner reuse", 'j', "[i for i in range(5) if (j := 0) for j in range(5)]"),
            ("Inner unpacking reuse", 'j', "[i for i in range(5) if (j := 0) for j, k in [(0, 1)]]"),
        ]
        for case, target, code in cases:
            msg = f"comprehension inner loop cannot rebind assignment expression target '{target}'"
            with self.subTest(case=case):
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(code, {}) # Module scope
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(code, {}, {}) # Class scope
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(f"lambda: {code}", {}) # Function scope

    def test_named_expression_invalid_list_comprehension_iterable_expression(self):
        cases = [
            ("Top level", "[i for i in (i := range(5))]"),
            ("Inside tuple", "[i for i in (2, 3, i := range(5))]"),
            ("Inside list", "[i for i in [2, 3, i := range(5)]]"),
            ("Different name", "[i for i in (j := range(5))]"),
            ("Lambda expression", "[i for i in (lambda:(j := range(5)))()]"),
            ("Inner loop", "[i for i in range(5) for j in (i := range(5))]"),
            ("Nested comprehension", "[i for i in [j for j in (k := range(5))]]"),
            ("Nested comprehension condition", "[i for i in [j for j in range(5) if (j := True)]]"),
            ("Nested comprehension body", "[i for i in [(j := True) for j in range(5)]]"),
        ]
        msg = "assignment expression cannot be used in a comprehension iterable expression"
        for case, code in cases:
            with self.subTest(case=case):
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(code, {}) # Module scope
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(code, {}, {}) # Class scope
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(f"lambda: {code}", {}) # Function scope

    def test_named_expression_invalid_rebinding_set_comprehension_iteration_variable(self):
        cases = [
            ("Local reuse", 'i', "{i := 0 for i in range(5)}"),
            ("Nested reuse", 'j', "{{(j := 0) for i in range(5)} for j in range(5)}"),
            ("Reuse inner loop target", 'j', "{(j := 0) for i in range(5) for j in range(5)}"),
            ("Unpacking reuse", 'i', "{i := 0 for i, j in {(0, 1)}}"),
            ("Reuse in loop condition", 'i', "{i+1 for i in range(5) if (i := 0)}"),
            ("Unreachable reuse", 'i', "{False or (i:=0) for i in range(5)}"),
            ("Unreachable nested reuse", 'i',
                "{(i, j) for i in range(5) for j in range(5) if True or (i:=10)}"),
            # Regression tests from https://github.com/python/cpython/issues/87447
            ("Complex expression: a", "a",
                "{(a := 1) for a, (*b, c[d+e::f(g)], h.i) in j}"),
            ("Complex expression: b", "b",
                "{(b := 1) for a, (*b, c[d+e::f(g)], h.i) in j}"),
        ]
        for case, target, code in cases:
            msg = f"assignment expression cannot rebind comprehension iteration variable '{target}'"
            with self.subTest(case=case):
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(code, {}) # Module scope
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(code, {}, {}) # Class scope
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(f"lambda: {code}", {}) # Function scope

    def test_named_expression_invalid_rebinding_set_comprehension_inner_loop(self):
        cases = [
            ("Inner reuse", 'j', "{i for i in range(5) if (j := 0) for j in range(5)}"),
            ("Inner unpacking reuse", 'j', "{i for i in range(5) if (j := 0) for j, k in {(0, 1)}}"),
        ]
        for case, target, code in cases:
            msg = f"comprehension inner loop cannot rebind assignment expression target '{target}'"
            with self.subTest(case=case):
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(code, {}) # Module scope
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(code, {}, {}) # Class scope
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(f"lambda: {code}", {}) # Function scope

    def test_named_expression_invalid_set_comprehension_iterable_expression(self):
        cases = [
            ("Top level", "{i for i in (i := range(5))}"),
            ("Inside tuple", "{i for i in (2, 3, i := range(5))}"),
            ("Inside list", "{i for i in {2, 3, i := range(5)}}"),
            ("Different name", "{i for i in (j := range(5))}"),
            ("Lambda expression", "{i for i in (lambda:(j := range(5)))()}"),
            ("Inner loop", "{i for i in range(5) for j in (i := range(5))}"),
            ("Nested comprehension", "{i for i in {j for j in (k := range(5))}}"),
            ("Nested comprehension condition", "{i for i in {j for j in range(5) if (j := True)}}"),
            ("Nested comprehension body", "{i for i in {(j := True) for j in range(5)}}"),
        ]
        msg = "assignment expression cannot be used in a comprehension iterable expression"
        for case, code in cases:
            with self.subTest(case=case):
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(code, {}) # Module scope
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(code, {}, {}) # Class scope
                with self.assertRaisesRegex(SyntaxError, msg):
                    exec(f"lambda: {code}", {}) # Function scope


class NamedExpressionAssignmentTest(unittest.TestCase):

    def test_named_expression_assignment_01(self):
        (a := 10)

        self.assertEqual(a, 10)

    def test_named_expression_assignment_02(self):
        a = 20
        (a := a)

        self.assertEqual(a, 20)

    def test_named_expression_assignment_03(self):
        (total := 1 + 2)

        self.assertEqual(total, 3)

    def test_named_expression_assignment_04(self):
        (info := (1, 2, 3))

        self.assertEqual(info, (1, 2, 3))

    def test_named_expression_assignment_05(self):
        (x := 1, 2)

        self.assertEqual(x, 1)

    def test_named_expression_assignment_06(self):
        (z := (y := (x := 0)))

        self.assertEqual(x, 0)
        self.assertEqual(y, 0)
        self.assertEqual(z, 0)

    def test_named_expression_assignment_07(self):
        (loc := (1, 2))

        self.assertEqual(loc, (1, 2))

    def test_named_expression_assignment_08(self):
        if spam := "eggs":
            self.assertEqual(spam, "eggs")
        else: self.fail("variable was not assigned using named expression")

    def test_named_expression_assignment_09(self):
        if True and (spam := True):
            self.assertTrue(spam)
        else: self.fail("variable was not assigned using named expression")

    def test_named_expression_assignment_10(self):
        if (match := 10) == 10:
            pass
        else: self.fail("variable was not assigned using named expression")

    def test_named_expression_assignment_11(self):
        def spam(a):
            return a
        input_data = [1, 2, 3]
        res = [(x, y, x/y) for x in input_data if (y := spam(x)) > 0]

        self.assertEqual(res, [(1, 1, 1.0), (2, 2, 1.0), (3, 3, 1.0)])

    def test_named_expression_assignment_12(self):
        def spam(a):
            return a
        res = [[y := spam(x), x/y] for x in range(1, 5)]

        self.assertEqual(res, [[1, 1.0], [2, 1.0], [3, 1.0], [4, 1.0]])

    def test_named_expression_assignment_13(self):
        length = len(lines := [1, 2])

        self.assertEqual(length, 2)
        self.assertEqual(lines, [1,2])

    def test_named_expression_assignment_14(self):
        """
        Where all variables are positive integers, and a is at least as large
        as the n'th root of x, this algorithm returns the floor of the n'th
        root of x (and roughly doubling the number of accurate bits per
        iteration):
        """
        a = 9
        n = 2
        x = 3

        while a > (d := x // a**(n-1)):
            a = ((n-1)*a + d) // n

        self.assertEqual(a, 1)

    def test_named_expression_assignment_15(self):
        while a := False:
            pass  # This will not run

        self.assertEqual(a, False)

    def test_named_expression_assignment_16(self):
        a, b = 1, 2
        fib = {(c := a): (a := b) + (b := a + c) - b for __ in range(6)}
        self.assertEqual(fib, {1: 2, 2: 3, 3: 5, 5: 8, 8: 13, 13: 21})

    def test_named_expression_assignment_17(self):
        a = [1]
        element = a[b:=0]
        self.assertEqual(b, 0)
        self.assertEqual(element, a[0])

    def test_named_expression_assignment_18(self):
        class TwoDimensionalList:
            def __init__(self, two_dimensional_list):
                self.two_dimensional_list = two_dimensional_list

            def __getitem__(self, index):
                return self.two_dimensional_list[index[0]][index[1]]

        a = TwoDimensionalList([[1], [2]])
        element = a[b:=0, c:=0]
        self.assertEqual(b, 0)
        self.assertEqual(c, 0)
        self.assertEqual(element, a.two_dimensional_list[b][c])



class NamedExpressionScopeTest(unittest.TestCase):

    def test_named_expression_scope_01(self):
        code = """def spam():
    (a := 5)
print(a)"""

        with self.assertRaisesRegex(NameError, "name 'a' is not defined"):
            exec(code, {}, {})

    def test_named_expression_scope_02(self):
        total = 0
        partial_sums = [total := total + v for v in range(5)]

        self.assertEqual(partial_sums, [0, 1, 3, 6, 10])
        self.assertEqual(total, 10)

    def test_named_expression_scope_03(self):
        containsOne = any((lastNum := num) == 1 for num in [1, 2, 3])

        self.assertTrue(containsOne)
        self.assertEqual(lastNum, 1)

    def test_named_expression_scope_04(self):
        def spam(a):
            return a
        res = [[y := spam(x), x/y] for x in range(1, 5)]

        self.assertEqual(y, 4)

    def test_named_expression_scope_05(self):
        def spam(a):
            return a
        input_data = [1, 2, 3]
        res = [(x, y, x/y) for x in input_data if (y := spam(x)) > 0]

        self.assertEqual(res, [(1, 1, 1.0), (2, 2, 1.0), (3, 3, 1.0)])
        self.assertEqual(y, 3)

    def test_named_expression_scope_06(self):
        res = [[spam := i for i in range(3)] for j in range(2)]

        self.assertEqual(res, [[0, 1, 2], [0, 1, 2]])
        self.assertEqual(spam, 2)

    def test_named_expression_scope_07(self):
        len(lines := [1, 2])

        self.assertEqual(lines, [1, 2])

    def test_named_expression_scope_08(self):
        def spam(a):
            return a

        def eggs(b):
            return b * 2

        res = [spam(a := eggs(b := h)) for h in range(2)]

        self.assertEqual(res, [0, 2])
        self.assertEqual(a, 2)
        self.assertEqual(b, 1)

    def test_named_expression_scope_09(self):
        def spam(a):
            return a

        def eggs(b):
            return b * 2

        res = [spam(a := eggs(a := h)) for h in range(2)]

        self.assertEqual(res, [0, 2])
        self.assertEqual(a, 2)

    def test_named_expression_scope_10(self):
        res = [b := [a := 1 for i in range(2)] for j in range(2)]

        self.assertEqual(res, [[1, 1], [1, 1]])
        self.assertEqual(a, 1)
        self.assertEqual(b, [1, 1])

    def test_named_expression_scope_11(self):
        res = [j := i for i in range(5)]

        self.assertEqual(res, [0, 1, 2, 3, 4])
        self.assertEqual(j, 4)

    def test_named_expression_scope_17(self):
        b = 0
        res = [b := i + b for i in range(5)]

        self.assertEqual(res, [0, 1, 3, 6, 10])
        self.assertEqual(b, 10)

    def test_named_expression_scope_18(self):
        def spam(a):
            return a

        res = spam(b := 2)

        self.assertEqual(res, 2)
        self.assertEqual(b, 2)

    def test_named_expression_scope_19(self):
        def spam(a):
            return a

        res = spam((b := 2))

        self.assertEqual(res, 2)
        self.assertEqual(b, 2)

    def test_named_expression_scope_20(self):
        def spam(a):
            return a

        res = spam(a=(b := 2))

        self.assertEqual(res, 2)
        self.assertEqual(b, 2)

    def test_named_expression_scope_21(self):
        def spam(a, b):
            return a + b

        res = spam(c := 2, b=1)

        self.assertEqual(res, 3)
        self.assertEqual(c, 2)

    def test_named_expression_scope_22(self):
        def spam(a, b):
            return a + b

        res = spam((c := 2), b=1)

        self.assertEqual(res, 3)
        self.assertEqual(c, 2)

    def test_named_expression_scope_23(self):
        def spam(a, b):
            return a + b

        res = spam(b=(c := 2), a=1)

        self.assertEqual(res, 3)
        self.assertEqual(c, 2)

    def test_named_expression_scope_24(self):
        a = 10
        def spam():
            nonlocal a
            (a := 20)
        spam()

        self.assertEqual(a, 20)

    def test_named_expression_scope_25(self):
        ns = {}
        code = """a = 10
def spam():
    global a
    (a := 20)
spam()"""

        exec(code, ns, {})

        self.assertEqual(ns["a"], 20)

    def test_named_expression_variable_reuse_in_comprehensions(self):
        # The compiler is expected to raise syntax error for comprehension
        # iteration variables, but should be fine with rebinding of other
        # names (e.g. globals, nonlocals, other assignment expressions)

        # The cases are all defined to produce the same expected result
        # Each comprehension is checked at both function scope and module scope
        rebinding = "[x := i for i in range(3) if (x := i) or not x]"
        filter_ref = "[x := i for i in range(3) if x or not x]"
        body_ref = "[x for i in range(3) if (x := i) or not x]"
        nested_ref = "[j for i in range(3) if x or not x for j in range(3) if (x := i)][:-3]"
        cases = [
            ("Rebind global", f"x = 1; result = {rebinding}"),
            ("Rebind nonlocal", f"result, x = (lambda x=1: ({rebinding}, x))()"),
            ("Filter global", f"x = 1; result = {filter_ref}"),
            ("Filter nonlocal", f"result, x = (lambda x=1: ({filter_ref}, x))()"),
            ("Body global", f"x = 1; result = {body_ref}"),
            ("Body nonlocal", f"result, x = (lambda x=1: ({body_ref}, x))()"),
            ("Nested global", f"x = 1; result = {nested_ref}"),
            ("Nested nonlocal", f"result, x = (lambda x=1: ({nested_ref}, x))()"),
        ]
        for case, code in cases:
            with self.subTest(case=case):
                ns = {}
                exec(code, ns)
                self.assertEqual(ns["x"], 2)
                self.assertEqual(ns["result"], [0, 1, 2])

    def test_named_expression_global_scope(self):
        sentinel = object()
        global GLOBAL_VAR
        def f():
            global GLOBAL_VAR
            [GLOBAL_VAR := sentinel for _ in range(1)]
            self.assertEqual(GLOBAL_VAR, sentinel)
        try:
            f()
            self.assertEqual(GLOBAL_VAR, sentinel)
        finally:
            GLOBAL_VAR = None

    def test_named_expression_global_scope_no_global_keyword(self):
        sentinel = object()
        def f():
            GLOBAL_VAR = None
            [GLOBAL_VAR := sentinel for _ in range(1)]
            self.assertEqual(GLOBAL_VAR, sentinel)
        f()
        self.assertEqual(GLOBAL_VAR, None)

    def test_named_expression_nonlocal_scope(self):
        sentinel = object()
        def f():
            nonlocal_var = None
            def g():
                nonlocal nonlocal_var
                [nonlocal_var := sentinel for _ in range(1)]
            g()
            self.assertEqual(nonlocal_var, sentinel)
        f()

    def test_named_expression_nonlocal_scope_no_nonlocal_keyword(self):
        sentinel = object()
        def f():
            nonlocal_var = None
            def g():
                [nonlocal_var := sentinel for _ in range(1)]
            g()
            self.assertEqual(nonlocal_var, None)
        f()

    def test_named_expression_scope_in_genexp(self):
        a = 1
        b = [1, 2, 3, 4]
        genexp = (c := i + a for i in b)

        self.assertNotIn("c", locals())
        for idx, elem in enumerate(genexp):
            self.assertEqual(elem, b[idx] + a)


if __name__ == "__main__":
    unittest.main()
import netrc, os, unittest, sys, textwrap
from test.support import os_helper, run_unittest

try:
    import pwd
except ImportError:
    pwd = None

temp_filename = os_helper.TESTFN

class NetrcTestCase(unittest.TestCase):

    def make_nrc(self, test_data):
        test_data = textwrap.dedent(test_data)
        mode = 'w'
        if sys.platform != 'cygwin':
            mode += 't'
        with open(temp_filename, mode, encoding="utf-8") as fp:
            fp.write(test_data)
        try:
            nrc = netrc.netrc(temp_filename)
        finally:
            os.unlink(temp_filename)
        return nrc

    def test_toplevel_non_ordered_tokens(self):
        nrc = self.make_nrc("""\
            machine host.domain.com password pass1 login log1 account acct1
            default login log2 password pass2 account acct2
            """)
        self.assertEqual(nrc.hosts['host.domain.com'], ('log1', 'acct1', 'pass1'))
        self.assertEqual(nrc.hosts['default'], ('log2', 'acct2', 'pass2'))

    def test_toplevel_tokens(self):
        nrc = self.make_nrc("""\
            machine host.domain.com login log1 password pass1 account acct1
            default login log2 password pass2 account acct2
            """)
        self.assertEqual(nrc.hosts['host.domain.com'], ('log1', 'acct1', 'pass1'))
        self.assertEqual(nrc.hosts['default'], ('log2', 'acct2', 'pass2'))

    def test_macros(self):
        data = """\
            macdef macro1
            line1
            line2

            macdef macro2
            line3
            line4

        """
        nrc = self.make_nrc(data)
        self.assertEqual(nrc.macros, {'macro1': ['line1\n', 'line2\n'],
                                      'macro2': ['line3\n', 'line4\n']})
        # strip the last \n
        self.assertRaises(netrc.NetrcParseError, self.make_nrc,
                          data.rstrip(' ')[:-1])

    def test_optional_tokens(self):
        data = (
            "machine host.domain.com",
            "machine host.domain.com login",
            "machine host.domain.com account",
            "machine host.domain.com password",
            "machine host.domain.com login \"\" account",
            "machine host.domain.com login \"\" password",
            "machine host.domain.com account \"\" password"
        )
        for item in data:
            nrc = self.make_nrc(item)
            self.assertEqual(nrc.hosts['host.domain.com'], ('', '', ''))
        data = (
            "default",
            "default login",
            "default account",
            "default password",
            "default login \"\" account",
            "default login \"\" password",
            "default account \"\" password"
        )
        for item in data:
            nrc = self.make_nrc(item)
            self.assertEqual(nrc.hosts['default'], ('', '', ''))

    def test_invalid_tokens(self):
        data = (
            "invalid host.domain.com",
            "machine host.domain.com invalid",
            "machine host.domain.com login log password pass account acct invalid",
            "default host.domain.com invalid",
            "default host.domain.com login log password pass account acct invalid"
        )
        for item in data:
            self.assertRaises(netrc.NetrcParseError, self.make_nrc, item)

    def _test_token_x(self, nrc, token, value):
        nrc = self.make_nrc(nrc)
        if token == 'login':
            self.assertEqual(nrc.hosts['host.domain.com'], (value, 'acct', 'pass'))
        elif token == 'account':
            self.assertEqual(nrc.hosts['host.domain.com'], ('log', value, 'pass'))
        elif token == 'password':
            self.assertEqual(nrc.hosts['host.domain.com'], ('log', 'acct', value))

    def test_token_value_quotes(self):
        self._test_token_x("""\
            machine host.domain.com login "log" password pass account acct
            """, 'login', 'log')
        self._test_token_x("""\
            machine host.domain.com login log password pass account "acct"
            """, 'account', 'acct')
        self._test_token_x("""\
            machine host.domain.com login log password "pass" account acct
            """, 'password', 'pass')

    def test_token_value_escape(self):
        self._test_token_x("""\
            machine host.domain.com login \\"log password pass account acct
            """, 'login', '"log')
        self._test_token_x("""\
            machine host.domain.com login "\\"log" password pass account acct
            """, 'login', '"log')
        self._test_token_x("""\
            machine host.domain.com login log password pass account \\"acct
            """, 'account', '"acct')
        self._test_token_x("""\
            machine host.domain.com login log password pass account "\\"acct"
            """, 'account', '"acct')
        self._test_token_x("""\
            machine host.domain.com login log password \\"pass account acct
            """, 'password', '"pass')
        self._test_token_x("""\
            machine host.domain.com login log password "\\"pass" account acct
            """, 'password', '"pass')

    def test_token_value_whitespace(self):
        self._test_token_x("""\
            machine host.domain.com login "lo g" password pass account acct
            """, 'login', 'lo g')
        self._test_token_x("""\
            machine host.domain.com login log password "pas s" account acct
            """, 'password', 'pas s')
        self._test_token_x("""\
            machine host.domain.com login log password pass account "acc t"
            """, 'account', 'acc t')

    def test_token_value_non_ascii(self):
        self._test_token_x("""\
            machine host.domain.com login \xa1\xa2 password pass account acct
            """, 'login', '\xa1\xa2')
        self._test_token_x("""\
            machine host.domain.com login log password pass account \xa1\xa2
            """, 'account', '\xa1\xa2')
        self._test_token_x("""\
            machine host.domain.com login log password \xa1\xa2 account acct
            """, 'password', '\xa1\xa2')

    def test_token_value_leading_hash(self):
        self._test_token_x("""\
            machine host.domain.com login #log password pass account acct
            """, 'login', '#log')
        self._test_token_x("""\
            machine host.domain.com login log password pass account #acct
            """, 'account', '#acct')
        self._test_token_x("""\
            machine host.domain.com login log password #pass account acct
            """, 'password', '#pass')

    def test_token_value_trailing_hash(self):
        self._test_token_x("""\
            machine host.domain.com login log# password pass account acct
            """, 'login', 'log#')
        self._test_token_x("""\
            machine host.domain.com login log password pass account acct#
            """, 'account', 'acct#')
        self._test_token_x("""\
            machine host.domain.com login log password pass# account acct
            """, 'password', 'pass#')

    def test_token_value_internal_hash(self):
        self._test_token_x("""\
            machine host.domain.com login lo#g password pass account acct
            """, 'login', 'lo#g')
        self._test_token_x("""\
            machine host.domain.com login log password pass account ac#ct
            """, 'account', 'ac#ct')
        self._test_token_x("""\
            machine host.domain.com login log password pa#ss account acct
            """, 'password', 'pa#ss')

    def _test_comment(self, nrc, passwd='pass'):
        nrc = self.make_nrc(nrc)
        self.assertEqual(nrc.hosts['foo.domain.com'], ('bar', '', passwd))
        self.assertEqual(nrc.hosts['bar.domain.com'], ('foo', '', 'pass'))

    def test_comment_before_machine_line(self):
        self._test_comment("""\
            # comment
            machine foo.domain.com login bar password pass
            machine bar.domain.com login foo password pass
            """)

    def test_comment_before_machine_line_no_space(self):
        self._test_comment("""\
            #comment
            machine foo.domain.com login bar password pass
            machine bar.domain.com login foo password pass
            """)

    def test_comment_before_machine_line_hash_only(self):
        self._test_comment("""\
            #
            machine foo.domain.com login bar password pass
            machine bar.domain.com login foo password pass
            """)

    def test_comment_after_machine_line(self):
        self._test_comment("""\
            machine foo.domain.com login bar password pass
            # comment
            machine bar.domain.com login foo password pass
            """)
        self._test_comment("""\
            machine foo.domain.com login bar password pass
            machine bar.domain.com login foo password pass
            # comment
            """)

    def test_comment_after_machine_line_no_space(self):
        self._test_comment("""\
            machine foo.domain.com login bar password pass
            #comment
            machine bar.domain.com login foo password pass
            """)
        self._test_comment("""\
            machine foo.domain.com login bar password pass
            machine bar.domain.com login foo password pass
            #comment
            """)

    def test_comment_after_machine_line_hash_only(self):
        self._test_comment("""\
            machine foo.domain.com login bar password pass
            #
            machine bar.domain.com login foo password pass
            """)
        self._test_comment("""\
            machine foo.domain.com login bar password pass
            machine bar.domain.com login foo password pass
            #
            """)

    def test_comment_at_end_of_machine_line(self):
        self._test_comment("""\
            machine foo.domain.com login bar password pass # comment
            machine bar.domain.com login foo password pass
            """)

    def test_comment_at_end_of_machine_line_no_space(self):
        self._test_comment("""\
            machine foo.domain.com login bar password pass #comment
            machine bar.domain.com login foo password pass
            """)

    def test_comment_at_end_of_machine_line_pass_has_hash(self):
        self._test_comment("""\
            machine foo.domain.com login bar password #pass #comment
            machine bar.domain.com login foo password pass
            """, '#pass')


    @unittest.skipUnless(os.name == 'posix', 'POSIX only test')
    @unittest.skipIf(pwd is None, 'security check requires pwd module')
    @os_helper.skip_unless_working_chmod
    def test_security(self):
        # This test is incomplete since we are normally not run as root and
        # therefore can't test the file ownership being wrong.
        d = os_helper.TESTFN
        os.mkdir(d)
        self.addCleanup(os_helper.rmtree, d)
        fn = os.path.join(d, '.netrc')
        with open(fn, 'wt') as f:
            f.write("""\
                machine foo.domain.com login bar password pass
                default login foo password pass
                """)
        with os_helper.EnvironmentVarGuard() as environ:
            environ.set('HOME', d)
            os.chmod(fn, 0o600)
            nrc = netrc.netrc()
            self.assertEqual(nrc.hosts['foo.domain.com'],
                             ('bar', '', 'pass'))
            os.chmod(fn, 0o622)
            self.assertRaises(netrc.NetrcParseError, netrc.netrc)
        with open(fn, 'wt') as f:
            f.write("""\
                machine foo.domain.com login anonymous password pass
                default login foo password pass
                """)
        with os_helper.EnvironmentVarGuard() as environ:
            environ.set('HOME', d)
            os.chmod(fn, 0o600)
            nrc = netrc.netrc()
            self.assertEqual(nrc.hosts['foo.domain.com'],
                             ('anonymous', '', 'pass'))
            os.chmod(fn, 0o622)
            self.assertEqual(nrc.hosts['foo.domain.com'],
                             ('anonymous', '', 'pass'))

def test_main():
    run_unittest(NetrcTestCase)

if __name__ == "__main__":
    test_main()
from test.support import import_helper
import unittest
import warnings


# Skip test if nis module does not exist.
with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    nis = import_helper.import_module('nis')


class NisTests(unittest.TestCase):
    def test_maps(self):
        try:
            maps = nis.maps()
        except nis.error as msg:
            # NIS is probably not active, so this test isn't useful
            self.skipTest(str(msg))
        try:
            # On some systems, this map is only accessible to the
            # super user
            maps.remove("passwd.adjunct.byname")
        except ValueError:
            pass

        done = 0
        for nismap in maps:
            mapping = nis.cat(nismap)
            for k, v in mapping.items():
                if not k:
                    continue
                if nis.match(k, nismap) != v:
                    self.fail("NIS match failed for key `%s' in map `%s'" % (k, nismap))
                else:
                    # just test the one key, otherwise this test could take a
                    # very long time
                    done = 1
                    break
            if done:
                break

if __name__ == '__main__':
    unittest.main()
import io
import socket
import datetime
import textwrap
import unittest
import functools
import contextlib
import os.path
import re
import threading

from test import support
from test.support import socket_helper, warnings_helper
nntplib = warnings_helper.import_deprecated("nntplib")
from nntplib import NNTP, GroupInfo
from unittest.mock import patch
try:
    import ssl
except ImportError:
    ssl = None


certfile = os.path.join(os.path.dirname(__file__), 'keycert3.pem')

if ssl is not None:
    SSLError = ssl.SSLError
else:
    class SSLError(Exception):
        """Non-existent exception class when we lack SSL support."""
        reason = "This will never be raised."

# TODO:
# - test the `file` arg to more commands
# - test error conditions
# - test auth and `usenetrc`


class NetworkedNNTPTestsMixin:

    ssl_context = None

    def test_welcome(self):
        welcome = self.server.getwelcome()
        self.assertEqual(str, type(welcome))

    def test_help(self):
        resp, lines = self.server.help()
        self.assertTrue(resp.startswith("100 "), resp)
        for line in lines:
            self.assertEqual(str, type(line))

    def test_list(self):
        resp, groups = self.server.list()
        if len(groups) > 0:
            self.assertEqual(GroupInfo, type(groups[0]))
            self.assertEqual(str, type(groups[0].group))

    def test_list_active(self):
        resp, groups = self.server.list(self.GROUP_PAT)
        if len(groups) > 0:
            self.assertEqual(GroupInfo, type(groups[0]))
            self.assertEqual(str, type(groups[0].group))

    def test_unknown_command(self):
        with self.assertRaises(nntplib.NNTPPermanentError) as cm:
            self.server._shortcmd("XYZZY")
        resp = cm.exception.response
        self.assertTrue(resp.startswith("500 "), resp)

    def test_newgroups(self):
        # gmane gets a constant influx of new groups.  In order not to stress
        # the server too much, we choose a recent date in the past.
        dt = datetime.date.today() - datetime.timedelta(days=7)
        resp, groups = self.server.newgroups(dt)
        if len(groups) > 0:
            self.assertIsInstance(groups[0], GroupInfo)
            self.assertIsInstance(groups[0].group, str)

    def test_description(self):
        def _check_desc(desc):
            # Sanity checks
            self.assertIsInstance(desc, str)
            self.assertNotIn(self.GROUP_NAME, desc)
        desc = self.server.description(self.GROUP_NAME)
        _check_desc(desc)
        # Another sanity check
        self.assertIn(self.DESC, desc)
        # With a pattern
        desc = self.server.description(self.GROUP_PAT)
        _check_desc(desc)
        # Shouldn't exist
        desc = self.server.description("zk.brrtt.baz")
        self.assertEqual(desc, '')

    def test_descriptions(self):
        resp, descs = self.server.descriptions(self.GROUP_PAT)
        # 215 for LIST NEWSGROUPS, 282 for XGTITLE
        self.assertTrue(
            resp.startswith("215 ") or resp.startswith("282 "), resp)
        self.assertIsInstance(descs, dict)
        desc = descs[self.GROUP_NAME]
        self.assertEqual(desc, self.server.description(self.GROUP_NAME))

    def test_group(self):
        result = self.server.group(self.GROUP_NAME)
        self.assertEqual(5, len(result))
        resp, count, first, last, group = result
        self.assertEqual(group, self.GROUP_NAME)
        self.assertIsInstance(count, int)
        self.assertIsInstance(first, int)
        self.assertIsInstance(last, int)
        self.assertLessEqual(first, last)
        self.assertTrue(resp.startswith("211 "), resp)

    def test_date(self):
        resp, date = self.server.date()
        self.assertIsInstance(date, datetime.datetime)
        # Sanity check
        self.assertGreaterEqual(date.year, 1995)
        self.assertLessEqual(date.year, 2030)

    def _check_art_dict(self, art_dict):
        # Some sanity checks for a field dictionary returned by OVER / XOVER
        self.assertIsInstance(art_dict, dict)
        # NNTP has 7 mandatory fields
        self.assertGreaterEqual(art_dict.keys(),
            {"subject", "from", "date", "message-id",
             "references", ":bytes", ":lines"}
            )
        for v in art_dict.values():
            self.assertIsInstance(v, (str, type(None)))

    def test_xover(self):
        resp, count, first, last, name = self.server.group(self.GROUP_NAME)
        resp, lines = self.server.xover(last - 5, last)
        if len(lines) == 0:
            self.skipTest("no articles retrieved")
        # The 'last' article is not necessarily part of the output (cancelled?)
        art_num, art_dict = lines[0]
        self.assertGreaterEqual(art_num, last - 5)
        self.assertLessEqual(art_num, last)
        self._check_art_dict(art_dict)

    @unittest.skipIf(True, 'temporarily skipped until a permanent solution'
                           ' is found for issue #28971')
    def test_over(self):
        resp, count, first, last, name = self.server.group(self.GROUP_NAME)
        start = last - 10
        # The "start-" article range form
        resp, lines = self.server.over((start, None))
        art_num, art_dict = lines[0]
        self._check_art_dict(art_dict)
        # The "start-end" article range form
        resp, lines = self.server.over((start, last))
        art_num, art_dict = lines[-1]
        # The 'last' article is not necessarily part of the output (cancelled?)
        self.assertGreaterEqual(art_num, start)
        self.assertLessEqual(art_num, last)
        self._check_art_dict(art_dict)
        # XXX The "message_id" form is unsupported by gmane
        # 503 Overview by message-ID unsupported

    def test_xhdr(self):
        resp, count, first, last, name = self.server.group(self.GROUP_NAME)
        resp, lines = self.server.xhdr('subject', last)
        for line in lines:
            self.assertEqual(str, type(line[1]))

    def check_article_resp(self, resp, article, art_num=None):
        self.assertIsInstance(article, nntplib.ArticleInfo)
        if art_num is not None:
            self.assertEqual(article.number, art_num)
        for line in article.lines:
            self.assertIsInstance(line, bytes)
        # XXX this could exceptionally happen...
        self.assertNotIn(article.lines[-1], (b".", b".\n", b".\r\n"))

    @unittest.skipIf(True, "FIXME: see bpo-32128")
    def test_article_head_body(self):
        resp, count, first, last, name = self.server.group(self.GROUP_NAME)
        # Try to find an available article
        for art_num in (last, first, last - 1):
            try:
                resp, head = self.server.head(art_num)
            except nntplib.NNTPTemporaryError as e:
                if not e.response.startswith("423 "):
                    raise
                # "423 No such article" => choose another one
                continue
            break
        else:
            self.skipTest("could not find a suitable article number")
        self.assertTrue(resp.startswith("221 "), resp)
        self.check_article_resp(resp, head, art_num)
        resp, body = self.server.body(art_num)
        self.assertTrue(resp.startswith("222 "), resp)
        self.check_article_resp(resp, body, art_num)
        resp, article = self.server.article(art_num)
        self.assertTrue(resp.startswith("220 "), resp)
        self.check_article_resp(resp, article, art_num)
        # Tolerate running the tests from behind a NNTP virus checker
        denylist = lambda line: line.startswith(b'X-Antivirus')
        filtered_head_lines = [line for line in head.lines
                               if not denylist(line)]
        filtered_lines = [line for line in article.lines
                          if not denylist(line)]
        self.assertEqual(filtered_lines, filtered_head_lines + [b''] + body.lines)

    def test_capabilities(self):
        # The server under test implements NNTP version 2 and has a
        # couple of well-known capabilities. Just sanity check that we
        # got them.
        def _check_caps(caps):
            caps_list = caps['LIST']
            self.assertIsInstance(caps_list, (list, tuple))
            self.assertIn('OVERVIEW.FMT', caps_list)
        self.assertGreaterEqual(self.server.nntp_version, 2)
        _check_caps(self.server.getcapabilities())
        # This re-emits the command
        resp, caps = self.server.capabilities()
        _check_caps(caps)

    def test_zlogin(self):
        # This test must be the penultimate because further commands will be
        # refused.
        baduser = "notarealuser"
        badpw = "notarealpassword"
        # Check that bogus credentials cause failure
        self.assertRaises(nntplib.NNTPError, self.server.login,
                          user=baduser, password=badpw, usenetrc=False)
        # FIXME: We should check that correct credentials succeed, but that
        # would require valid details for some server somewhere to be in the
        # test suite, I think. Gmane is anonymous, at least as used for the
        # other tests.

    def test_zzquit(self):
        # This test must be called last, hence the name
        cls = type(self)
        try:
            self.server.quit()
        finally:
            cls.server = None

    @classmethod
    def wrap_methods(cls):
        # Wrap all methods in a transient_internet() exception catcher
        # XXX put a generic version in test.support?
        def wrap_meth(meth):
            @functools.wraps(meth)
            def wrapped(self):
                with socket_helper.transient_internet(self.NNTP_HOST):
                    meth(self)
            return wrapped
        for name in dir(cls):
            if not name.startswith('test_'):
                continue
            meth = getattr(cls, name)
            if not callable(meth):
                continue
            # Need to use a closure so that meth remains bound to its current
            # value
            setattr(cls, name, wrap_meth(meth))

    def test_timeout(self):
        with self.assertRaises(ValueError):
            self.NNTP_CLASS(self.NNTP_HOST, timeout=0, usenetrc=False)

    def test_with_statement(self):
        def is_connected():
            if not hasattr(server, 'file'):
                return False
            try:
                server.help()
            except (OSError, EOFError):
                return False
            return True

        kwargs = dict(
            timeout=support.INTERNET_TIMEOUT,
            usenetrc=False
        )
        if self.ssl_context is not None:
            kwargs["ssl_context"] = self.ssl_context

        try:
            server = self.NNTP_CLASS(self.NNTP_HOST, **kwargs)
            with server:
                self.assertTrue(is_connected())
                self.assertTrue(server.help())
            self.assertFalse(is_connected())

            server = self.NNTP_CLASS(self.NNTP_HOST, **kwargs)
            with server:
                server.quit()
            self.assertFalse(is_connected())
        except SSLError as ssl_err:
            # matches "[SSL: DH_KEY_TOO_SMALL] dh key too small"
            if re.search(r'(?i)KEY.TOO.SMALL', ssl_err.reason):
                raise unittest.SkipTest(f"Got {ssl_err} connecting "
                                        f"to {self.NNTP_HOST!r}")
            raise


NetworkedNNTPTestsMixin.wrap_methods()


EOF_ERRORS = (EOFError,)
if ssl is not None:
    EOF_ERRORS += (ssl.SSLEOFError,)


class NetworkedNNTPTests(NetworkedNNTPTestsMixin, unittest.TestCase):
    # This server supports STARTTLS (gmane doesn't)
    NNTP_HOST = 'news.trigofacile.com'
    GROUP_NAME = 'fr.comp.lang.python'
    GROUP_PAT = 'fr.comp.lang.*'
    DESC = 'Python'

    NNTP_CLASS = NNTP

    @classmethod
    def setUpClass(cls):
        support.requires("network")
        kwargs = dict(
            timeout=support.INTERNET_TIMEOUT,
            usenetrc=False
        )
        if cls.ssl_context is not None:
            kwargs["ssl_context"] = cls.ssl_context
        with socket_helper.transient_internet(cls.NNTP_HOST):
            try:
                cls.server = cls.NNTP_CLASS(cls.NNTP_HOST, **kwargs)
            except SSLError as ssl_err:
                # matches "[SSL: DH_KEY_TOO_SMALL] dh key too small"
                if re.search(r'(?i)KEY.TOO.SMALL', ssl_err.reason):
                    raise unittest.SkipTest(f"{cls} got {ssl_err} connecting "
                                            f"to {cls.NNTP_HOST!r}")
                print(cls.NNTP_HOST)
                raise
            except EOF_ERRORS:
                raise unittest.SkipTest(f"{cls} got EOF error on connecting "
                                        f"to {cls.NNTP_HOST!r}")

    @classmethod
    def tearDownClass(cls):
        if cls.server is not None:
            cls.server.quit()

@unittest.skipUnless(ssl, 'requires SSL support')
class NetworkedNNTP_SSLTests(NetworkedNNTPTests):

    # Technical limits for this public NNTP server (see http://www.aioe.org):
    # "Only two concurrent connections per IP address are allowed and
    # 400 connections per day are accepted from each IP address."

    NNTP_HOST = 'nntp.aioe.org'
    # bpo-42794: aioe.test is one of the official groups on this server
    # used for testing: https://news.aioe.org/manual/aioe-hierarchy/
    GROUP_NAME = 'aioe.test'
    GROUP_PAT = 'aioe.*'
    DESC = 'test'

    NNTP_CLASS = getattr(nntplib, 'NNTP_SSL', None)

    # Disabled as it produces too much data
    test_list = None

    # Disabled as the connection will already be encrypted.
    test_starttls = None

    if ssl is not None:
        ssl_context = ssl._create_unverified_context()
        ssl_context.set_ciphers("DEFAULT")
        ssl_context.maximum_version = ssl.TLSVersion.TLSv1_2

#
# Non-networked tests using a local server (or something mocking it).
#

class _NNTPServerIO(io.RawIOBase):
    """A raw IO object allowing NNTP commands to be received and processed
    by a handler.  The handler can push responses which can then be read
    from the IO object."""

    def __init__(self, handler):
        io.RawIOBase.__init__(self)
        # The channel from the client
        self.c2s = io.BytesIO()
        # The channel to the client
        self.s2c = io.BytesIO()
        self.handler = handler
        self.handler.start(self.c2s.readline, self.push_data)

    def readable(self):
        return True

    def writable(self):
        return True

    def push_data(self, data):
        """Push (buffer) some data to send to the client."""
        pos = self.s2c.tell()
        self.s2c.seek(0, 2)
        self.s2c.write(data)
        self.s2c.seek(pos)

    def write(self, b):
        """The client sends us some data"""
        pos = self.c2s.tell()
        self.c2s.write(b)
        self.c2s.seek(pos)
        self.handler.process_pending()
        return len(b)

    def readinto(self, buf):
        """The client wants to read a response"""
        self.handler.process_pending()
        b = self.s2c.read(len(buf))
        n = len(b)
        buf[:n] = b
        return n


def make_mock_file(handler):
    sio = _NNTPServerIO(handler)
    # Using BufferedRWPair instead of BufferedRandom ensures the file
    # isn't seekable.
    file = io.BufferedRWPair(sio, sio)
    return (sio, file)


class NNTPServer(nntplib.NNTP):

    def __init__(self, f, host, readermode=None):
        self.file = f
        self.host = host
        self._base_init(readermode)

    def _close(self):
        self.file.close()
        del self.file


class MockedNNTPTestsMixin:
    # Override in derived classes
    handler_class = None

    def setUp(self):
        super().setUp()
        self.make_server()

    def tearDown(self):
        super().tearDown()
        del self.server

    def make_server(self, *args, **kwargs):
        self.handler = self.handler_class()
        self.sio, file = make_mock_file(self.handler)
        self.server = NNTPServer(file, 'test.server', *args, **kwargs)
        return self.server


class MockedNNTPWithReaderModeMixin(MockedNNTPTestsMixin):
    def setUp(self):
        super().setUp()
        self.make_server(readermode=True)


class NNTPv1Handler:
    """A handler for RFC 977"""

    welcome = "200 NNTP mock server"

    def start(self, readline, push_data):
        self.in_body = False
        self.allow_posting = True
        self._readline = readline
        self._push_data = push_data
        self._logged_in = False
        self._user_sent = False
        # Our welcome
        self.handle_welcome()

    def _decode(self, data):
        return str(data, "utf-8", "surrogateescape")

    def process_pending(self):
        if self.in_body:
            while True:
                line = self._readline()
                if not line:
                    return
                self.body.append(line)
                if line == b".\r\n":
                    break
            try:
                meth, tokens = self.body_callback
                meth(*tokens, body=self.body)
            finally:
                self.body_callback = None
                self.body = None
                self.in_body = False
        while True:
            line = self._decode(self._readline())
            if not line:
                return
            if not line.endswith("\r\n"):
                raise ValueError("line doesn't end with \\r\\n: {!r}".format(line))
            line = line[:-2]
            cmd, *tokens = line.split()
            #meth = getattr(self.handler, "handle_" + cmd.upper(), None)
            meth = getattr(self, "handle_" + cmd.upper(), None)
            if meth is None:
                self.handle_unknown()
            else:
                try:
                    meth(*tokens)
                except Exception as e:
                    raise ValueError("command failed: {!r}".format(line)) from e
                else:
                    if self.in_body:
                        self.body_callback = meth, tokens
                        self.body = []

    def expect_body(self):
        """Flag that the client is expected to post a request body"""
        self.in_body = True

    def push_data(self, data):
        """Push some binary data"""
        self._push_data(data)

    def push_lit(self, lit):
        """Push a string literal"""
        lit = textwrap.dedent(lit)
        lit = "\r\n".join(lit.splitlines()) + "\r\n"
        lit = lit.encode('utf-8')
        self.push_data(lit)

    def handle_unknown(self):
        self.push_lit("500 What?")

    def handle_welcome(self):
        self.push_lit(self.welcome)

    def handle_QUIT(self):
        self.push_lit("205 Bye!")

    def handle_DATE(self):
        self.push_lit("111 20100914001155")

    def handle_GROUP(self, group):
        if group == "fr.comp.lang.python":
            self.push_lit("211 486 761 1265 fr.comp.lang.python")
        else:
            self.push_lit("411 No such group {}".format(group))

    def handle_HELP(self):
        self.push_lit("""\
            100 Legal commands
              authinfo user Name|pass Password|generic <prog> <args>
              date
              help
            Report problems to <root@example.org>
            .""")

    def handle_STAT(self, message_spec=None):
        if message_spec is None:
            self.push_lit("412 No newsgroup selected")
        elif message_spec == "3000234":
            self.push_lit("223 3000234 <45223423@example.com>")
        elif message_spec == "<45223423@example.com>":
            self.push_lit("223 0 <45223423@example.com>")
        else:
            self.push_lit("430 No Such Article Found")

    def handle_NEXT(self):
        self.push_lit("223 3000237 <668929@example.org> retrieved")

    def handle_LAST(self):
        self.push_lit("223 3000234 <45223423@example.com> retrieved")

    def handle_LIST(self, action=None, param=None):
        if action is None:
            self.push_lit("""\
                215 Newsgroups in form "group high low flags".
                comp.lang.python 0000052340 0000002828 y
                comp.lang.python.announce 0000001153 0000000993 m
                free.it.comp.lang.python 0000000002 0000000002 y
                fr.comp.lang.python 0000001254 0000000760 y
                free.it.comp.lang.python.learner 0000000000 0000000001 y
                tw.bbs.comp.lang.python 0000000304 0000000304 y
                .""")
        elif action == "ACTIVE":
            if param == "*distutils*":
                self.push_lit("""\
                    215 Newsgroups in form "group high low flags"
                    gmane.comp.python.distutils.devel 0000014104 0000000001 m
                    gmane.comp.python.distutils.cvs 0000000000 0000000001 m
                    .""")
            else:
                self.push_lit("""\
                    215 Newsgroups in form "group high low flags"
                    .""")
        elif action == "OVERVIEW.FMT":
            self.push_lit("""\
                215 Order of fields in overview database.
                Subject:
                From:
                Date:
                Message-ID:
                References:
                Bytes:
                Lines:
                Xref:full
                .""")
        elif action == "NEWSGROUPS":
            assert param is not None
            if param == "comp.lang.python":
                self.push_lit("""\
                    215 Descriptions in form "group description".
                    comp.lang.python\tThe Python computer language.
                    .""")
            elif param == "comp.lang.python*":
                self.push_lit("""\
                    215 Descriptions in form "group description".
                    comp.lang.python.announce\tAnnouncements about the Python language. (Moderated)
                    comp.lang.python\tThe Python computer language.
                    .""")
            else:
                self.push_lit("""\
                    215 Descriptions in form "group description".
                    .""")
        else:
            self.push_lit('501 Unknown LIST keyword')

    def handle_NEWNEWS(self, group, date_str, time_str):
        # We hard code different return messages depending on passed
        # argument and date syntax.
        if (group == "comp.lang.python" and date_str == "20100913"
            and time_str == "082004"):
            # Date was passed in RFC 3977 format (NNTP "v2")
            self.push_lit("""\
                230 list of newsarticles (NNTP v2) created after Mon Sep 13 08:20:04 2010 follows
                <a4929a40-6328-491a-aaaf-cb79ed7309a2@q2g2000vbk.googlegroups.com>
                <f30c0419-f549-4218-848f-d7d0131da931@y3g2000vbm.googlegroups.com>
                .""")
        elif (group == "comp.lang.python" and date_str == "100913"
            and time_str == "082004"):
            # Date was passed in RFC 977 format (NNTP "v1")
            self.push_lit("""\
                230 list of newsarticles (NNTP v1) created after Mon Sep 13 08:20:04 2010 follows
                <a4929a40-6328-491a-aaaf-cb79ed7309a2@q2g2000vbk.googlegroups.com>
                <f30c0419-f549-4218-848f-d7d0131da931@y3g2000vbm.googlegroups.com>
                .""")
        elif (group == 'comp.lang.python' and
              date_str in ('20100101', '100101') and
              time_str == '090000'):
            self.push_lit('too long line' * 3000 +
                          '\n.')
        else:
            self.push_lit("""\
                230 An empty list of newsarticles follows
                .""")
        # (Note for experiments: many servers disable NEWNEWS.
        #  As of this writing, sicinfo3.epfl.ch doesn't.)

    def handle_XOVER(self, message_spec):
        if message_spec == "57-59":
            self.push_lit(
                "224 Overview information for 57-58 follows\n"
                "57\tRe: ANN: New Plone book with strong Python (and Zope) themes throughout"
                    "\tDoug Hellmann <doug.hellmann-Re5JQEeQqe8AvxtiuMwx3w@public.gmane.org>"
                    "\tSat, 19 Jun 2010 18:04:08 -0400"
                    "\t<4FD05F05-F98B-44DC-8111-C6009C925F0C@gmail.com>"
                    "\t<hvalf7$ort$1@dough.gmane.org>\t7103\t16"
                    "\tXref: news.gmane.io gmane.comp.python.authors:57"
                    "\n"
                "58\tLooking for a few good bloggers"
                    "\tDoug Hellmann <doug.hellmann-Re5JQEeQqe8AvxtiuMwx3w@public.gmane.org>"
                    "\tThu, 22 Jul 2010 09:14:14 -0400"
                    "\t<A29863FA-F388-40C3-AA25-0FD06B09B5BF@gmail.com>"
                    "\t\t6683\t16"
                    "\t"
                    "\n"
                # A UTF-8 overview line from fr.comp.lang.python
                "59\tRe: Message d'erreur incompréhensible (par moi)"
                    "\tEric Brunel <eric.brunel@pragmadev.nospam.com>"
                    "\tWed, 15 Sep 2010 18:09:15 +0200"
                    "\t<eric.brunel-2B8B56.18091515092010@news.wanadoo.fr>"
                    "\t<4c90ec87$0$32425$ba4acef3@reader.news.orange.fr>\t1641\t27"
                    "\tXref: saria.nerim.net fr.comp.lang.python:1265"
                    "\n"
                ".\n")
        else:
            self.push_lit("""\
                224 No articles
                .""")

    def handle_POST(self, *, body=None):
        if body is None:
            if self.allow_posting:
                self.push_lit("340 Input article; end with <CR-LF>.<CR-LF>")
                self.expect_body()
            else:
                self.push_lit("440 Posting not permitted")
        else:
            assert self.allow_posting
            self.push_lit("240 Article received OK")
            self.posted_body = body

    def handle_IHAVE(self, message_id, *, body=None):
        if body is None:
            if (self.allow_posting and
                message_id == "<i.am.an.article.you.will.want@example.com>"):
                self.push_lit("335 Send it; end with <CR-LF>.<CR-LF>")
                self.expect_body()
            else:
                self.push_lit("435 Article not wanted")
        else:
            assert self.allow_posting
            self.push_lit("235 Article transferred OK")
            self.posted_body = body

    sample_head = """\
        From: "Demo User" <nobody@example.net>
        Subject: I am just a test article
        Content-Type: text/plain; charset=UTF-8; format=flowed
        Message-ID: <i.am.an.article.you.will.want@example.com>"""

    sample_body = """\
        This is just a test article.
        ..Here is a dot-starting line.

        -- Signed by Andr\xe9."""

    sample_article = sample_head + "\n\n" + sample_body

    def handle_ARTICLE(self, message_spec=None):
        if message_spec is None:
            self.push_lit("220 3000237 <45223423@example.com>")
        elif message_spec == "<45223423@example.com>":
            self.push_lit("220 0 <45223423@example.com>")
        elif message_spec == "3000234":
            self.push_lit("220 3000234 <45223423@example.com>")
        else:
            self.push_lit("430 No Such Article Found")
            return
        self.push_lit(self.sample_article)
        self.push_lit(".")

    def handle_HEAD(self, message_spec=None):
        if message_spec is None:
            self.push_lit("221 3000237 <45223423@example.com>")
        elif message_spec == "<45223423@example.com>":
            self.push_lit("221 0 <45223423@example.com>")
        elif message_spec == "3000234":
            self.push_lit("221 3000234 <45223423@example.com>")
        else:
            self.push_lit("430 No Such Article Found")
            return
        self.push_lit(self.sample_head)
        self.push_lit(".")

    def handle_BODY(self, message_spec=None):
        if message_spec is None:
            self.push_lit("222 3000237 <45223423@example.com>")
        elif message_spec == "<45223423@example.com>":
            self.push_lit("222 0 <45223423@example.com>")
        elif message_spec == "3000234":
            self.push_lit("222 3000234 <45223423@example.com>")
        else:
            self.push_lit("430 No Such Article Found")
            return
        self.push_lit(self.sample_body)
        self.push_lit(".")

    def handle_AUTHINFO(self, cred_type, data):
        if self._logged_in:
            self.push_lit('502 Already Logged In')
        elif cred_type == 'user':
            if self._user_sent:
                self.push_lit('482 User Credential Already Sent')
            else:
                self.push_lit('381 Password Required')
                self._user_sent = True
        elif cred_type == 'pass':
            self.push_lit('281 Login Successful')
            self._logged_in = True
        else:
            raise Exception('Unknown cred type {}'.format(cred_type))


class NNTPv2Handler(NNTPv1Handler):
    """A handler for RFC 3977 (NNTP "v2")"""

    def handle_CAPABILITIES(self):
        fmt = """\
            101 Capability list:
            VERSION 2 3
            IMPLEMENTATION INN 2.5.1{}
            HDR
            LIST ACTIVE ACTIVE.TIMES DISTRIB.PATS HEADERS NEWSGROUPS OVERVIEW.FMT
            OVER
            POST
            READER
            ."""

        if not self._logged_in:
            self.push_lit(fmt.format('\n            AUTHINFO USER'))
        else:
            self.push_lit(fmt.format(''))

    def handle_MODE(self, _):
        raise Exception('MODE READER sent despite READER has been advertised')

    def handle_OVER(self, message_spec=None):
        return self.handle_XOVER(message_spec)


class CapsAfterLoginNNTPv2Handler(NNTPv2Handler):
    """A handler that allows CAPABILITIES only after login"""

    def handle_CAPABILITIES(self):
        if not self._logged_in:
            self.push_lit('480 You must log in.')
        else:
            super().handle_CAPABILITIES()


class ModeSwitchingNNTPv2Handler(NNTPv2Handler):
    """A server that starts in transit mode"""

    def __init__(self):
        self._switched = False

    def handle_CAPABILITIES(self):
        fmt = """\
            101 Capability list:
            VERSION 2 3
            IMPLEMENTATION INN 2.5.1
            HDR
            LIST ACTIVE ACTIVE.TIMES DISTRIB.PATS HEADERS NEWSGROUPS OVERVIEW.FMT
            OVER
            POST
            {}READER
            ."""
        if self._switched:
            self.push_lit(fmt.format(''))
        else:
            self.push_lit(fmt.format('MODE-'))

    def handle_MODE(self, what):
        assert not self._switched and what == 'reader'
        self._switched = True
        self.push_lit('200 Posting allowed')


class NNTPv1v2TestsMixin:

    def setUp(self):
        super().setUp()

    def test_welcome(self):
        self.assertEqual(self.server.welcome, self.handler.welcome)

    def test_authinfo(self):
        if self.nntp_version == 2:
            self.assertIn('AUTHINFO', self.server._caps)
        self.server.login('testuser', 'testpw')
        # if AUTHINFO is gone from _caps we also know that getcapabilities()
        # has been called after login as it should
        self.assertNotIn('AUTHINFO', self.server._caps)

    def test_date(self):
        resp, date = self.server.date()
        self.assertEqual(resp, "111 20100914001155")
        self.assertEqual(date, datetime.datetime(2010, 9, 14, 0, 11, 55))

    def test_quit(self):
        self.assertFalse(self.sio.closed)
        resp = self.server.quit()
        self.assertEqual(resp, "205 Bye!")
        self.assertTrue(self.sio.closed)

    def test_help(self):
        resp, help = self.server.help()
        self.assertEqual(resp, "100 Legal commands")
        self.assertEqual(help, [
            '  authinfo user Name|pass Password|generic <prog> <args>',
            '  date',
            '  help',
            'Report problems to <root@example.org>',
        ])

    def test_list(self):
        resp, groups = self.server.list()
        self.assertEqual(len(groups), 6)
        g = groups[1]
        self.assertEqual(g,
            GroupInfo("comp.lang.python.announce", "0000001153",
                      "0000000993", "m"))
        resp, groups = self.server.list("*distutils*")
        self.assertEqual(len(groups), 2)
        g = groups[0]
        self.assertEqual(g,
            GroupInfo("gmane.comp.python.distutils.devel", "0000014104",
                      "0000000001", "m"))

    def test_stat(self):
        resp, art_num, message_id = self.server.stat(3000234)
        self.assertEqual(resp, "223 3000234 <45223423@example.com>")
        self.assertEqual(art_num, 3000234)
        self.assertEqual(message_id, "<45223423@example.com>")
        resp, art_num, message_id = self.server.stat("<45223423@example.com>")
        self.assertEqual(resp, "223 0 <45223423@example.com>")
        self.assertEqual(art_num, 0)
        self.assertEqual(message_id, "<45223423@example.com>")
        with self.assertRaises(nntplib.NNTPTemporaryError) as cm:
            self.server.stat("<non.existent.id>")
        self.assertEqual(cm.exception.response, "430 No Such Article Found")
        with self.assertRaises(nntplib.NNTPTemporaryError) as cm:
            self.server.stat()
        self.assertEqual(cm.exception.response, "412 No newsgroup selected")

    def test_next(self):
        resp, art_num, message_id = self.server.next()
        self.assertEqual(resp, "223 3000237 <668929@example.org> retrieved")
        self.assertEqual(art_num, 3000237)
        self.assertEqual(message_id, "<668929@example.org>")

    def test_last(self):
        resp, art_num, message_id = self.server.last()
        self.assertEqual(resp, "223 3000234 <45223423@example.com> retrieved")
        self.assertEqual(art_num, 3000234)
        self.assertEqual(message_id, "<45223423@example.com>")

    def test_description(self):
        desc = self.server.description("comp.lang.python")
        self.assertEqual(desc, "The Python computer language.")
        desc = self.server.description("comp.lang.pythonx")
        self.assertEqual(desc, "")

    def test_descriptions(self):
        resp, groups = self.server.descriptions("comp.lang.python")
        self.assertEqual(resp, '215 Descriptions in form "group description".')
        self.assertEqual(groups, {
            "comp.lang.python": "The Python computer language.",
            })
        resp, groups = self.server.descriptions("comp.lang.python*")
        self.assertEqual(groups, {
            "comp.lang.python": "The Python computer language.",
            "comp.lang.python.announce": "Announcements about the Python language. (Moderated)",
            })
        resp, groups = self.server.descriptions("comp.lang.pythonx")
        self.assertEqual(groups, {})

    def test_group(self):
        resp, count, first, last, group = self.server.group("fr.comp.lang.python")
        self.assertTrue(resp.startswith("211 "), resp)
        self.assertEqual(first, 761)
        self.assertEqual(last, 1265)
        self.assertEqual(count, 486)
        self.assertEqual(group, "fr.comp.lang.python")
        with self.assertRaises(nntplib.NNTPTemporaryError) as cm:
            self.server.group("comp.lang.python.devel")
        exc = cm.exception
        self.assertTrue(exc.response.startswith("411 No such group"),
                        exc.response)

    def test_newnews(self):
        # NEWNEWS comp.lang.python [20]100913 082004
        dt = datetime.datetime(2010, 9, 13, 8, 20, 4)
        resp, ids = self.server.newnews("comp.lang.python", dt)
        expected = (
            "230 list of newsarticles (NNTP v{0}) "
            "created after Mon Sep 13 08:20:04 2010 follows"
            ).format(self.nntp_version)
        self.assertEqual(resp, expected)
        self.assertEqual(ids, [
            "<a4929a40-6328-491a-aaaf-cb79ed7309a2@q2g2000vbk.googlegroups.com>",
            "<f30c0419-f549-4218-848f-d7d0131da931@y3g2000vbm.googlegroups.com>",
            ])
        # NEWNEWS fr.comp.lang.python [20]100913 082004
        dt = datetime.datetime(2010, 9, 13, 8, 20, 4)
        resp, ids = self.server.newnews("fr.comp.lang.python", dt)
        self.assertEqual(resp, "230 An empty list of newsarticles follows")
        self.assertEqual(ids, [])

    def _check_article_body(self, lines):
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[-1].decode('utf-8'), "-- Signed by André.")
        self.assertEqual(lines[-2], b"")
        self.assertEqual(lines[-3], b".Here is a dot-starting line.")
        self.assertEqual(lines[-4], b"This is just a test article.")

    def _check_article_head(self, lines):
        self.assertEqual(len(lines), 4)
        self.assertEqual(lines[0], b'From: "Demo User" <nobody@example.net>')
        self.assertEqual(lines[3], b"Message-ID: <i.am.an.article.you.will.want@example.com>")

    def _check_article_data(self, lines):
        self.assertEqual(len(lines), 9)
        self._check_article_head(lines[:4])
        self._check_article_body(lines[-4:])
        self.assertEqual(lines[4], b"")

    def test_article(self):
        # ARTICLE
        resp, info = self.server.article()
        self.assertEqual(resp, "220 3000237 <45223423@example.com>")
        art_num, message_id, lines = info
        self.assertEqual(art_num, 3000237)
        self.assertEqual(message_id, "<45223423@example.com>")
        self._check_article_data(lines)
        # ARTICLE num
        resp, info = self.server.article(3000234)
        self.assertEqual(resp, "220 3000234 <45223423@example.com>")
        art_num, message_id, lines = info
        self.assertEqual(art_num, 3000234)
        self.assertEqual(message_id, "<45223423@example.com>")
        self._check_article_data(lines)
        # ARTICLE id
        resp, info = self.server.article("<45223423@example.com>")
        self.assertEqual(resp, "220 0 <45223423@example.com>")
        art_num, message_id, lines = info
        self.assertEqual(art_num, 0)
        self.assertEqual(message_id, "<45223423@example.com>")
        self._check_article_data(lines)
        # Non-existent id
        with self.assertRaises(nntplib.NNTPTemporaryError) as cm:
            self.server.article("<non-existent@example.com>")
        self.assertEqual(cm.exception.response, "430 No Such Article Found")

    def test_article_file(self):
        # With a "file" argument
        f = io.BytesIO()
        resp, info = self.server.article(file=f)
        self.assertEqual(resp, "220 3000237 <45223423@example.com>")
        art_num, message_id, lines = info
        self.assertEqual(art_num, 3000237)
        self.assertEqual(message_id, "<45223423@example.com>")
        self.assertEqual(lines, [])
        data = f.getvalue()
        self.assertTrue(data.startswith(
            b'From: "Demo User" <nobody@example.net>\r\n'
            b'Subject: I am just a test article\r\n'
            ), ascii(data))
        self.assertTrue(data.endswith(
            b'This is just a test article.\r\n'
            b'.Here is a dot-starting line.\r\n'
            b'\r\n'
            b'-- Signed by Andr\xc3\xa9.\r\n'
            ), ascii(data))

    def test_head(self):
        # HEAD
        resp, info = self.server.head()
        self.assertEqual(resp, "221 3000237 <45223423@example.com>")
        art_num, message_id, lines = info
        self.assertEqual(art_num, 3000237)
        self.assertEqual(message_id, "<45223423@example.com>")
        self._check_article_head(lines)
        # HEAD num
        resp, info = self.server.head(3000234)
        self.assertEqual(resp, "221 3000234 <45223423@example.com>")
        art_num, message_id, lines = info
        self.assertEqual(art_num, 3000234)
        self.assertEqual(message_id, "<45223423@example.com>")
        self._check_article_head(lines)
        # HEAD id
        resp, info = self.server.head("<45223423@example.com>")
        self.assertEqual(resp, "221 0 <45223423@example.com>")
        art_num, message_id, lines = info
        self.assertEqual(art_num, 0)
        self.assertEqual(message_id, "<45223423@example.com>")
        self._check_article_head(lines)
        # Non-existent id
        with self.assertRaises(nntplib.NNTPTemporaryError) as cm:
            self.server.head("<non-existent@example.com>")
        self.assertEqual(cm.exception.response, "430 No Such Article Found")

    def test_head_file(self):
        f = io.BytesIO()
        resp, info = self.server.head(file=f)
        self.assertEqual(resp, "221 3000237 <45223423@example.com>")
        art_num, message_id, lines = info
        self.assertEqual(art_num, 3000237)
        self.assertEqual(message_id, "<45223423@example.com>")
        self.assertEqual(lines, [])
        data = f.getvalue()
        self.assertTrue(data.startswith(
            b'From: "Demo User" <nobody@example.net>\r\n'
            b'Subject: I am just a test article\r\n'
            ), ascii(data))
        self.assertFalse(data.endswith(
            b'This is just a test article.\r\n'
            b'.Here is a dot-starting line.\r\n'
            b'\r\n'
            b'-- Signed by Andr\xc3\xa9.\r\n'
            ), ascii(data))

    def test_body(self):
        # BODY
        resp, info = self.server.body()
        self.assertEqual(resp, "222 3000237 <45223423@example.com>")
        art_num, message_id, lines = info
        self.assertEqual(art_num, 3000237)
        self.assertEqual(message_id, "<45223423@example.com>")
        self._check_article_body(lines)
        # BODY num
        resp, info = self.server.body(3000234)
        self.assertEqual(resp, "222 3000234 <45223423@example.com>")
        art_num, message_id, lines = info
        self.assertEqual(art_num, 3000234)
        self.assertEqual(message_id, "<45223423@example.com>")
        self._check_article_body(lines)
        # BODY id
        resp, info = self.server.body("<45223423@example.com>")
        self.assertEqual(resp, "222 0 <45223423@example.com>")
        art_num, message_id, lines = info
        self.assertEqual(art_num, 0)
        self.assertEqual(message_id, "<45223423@example.com>")
        self._check_article_body(lines)
        # Non-existent id
        with self.assertRaises(nntplib.NNTPTemporaryError) as cm:
            self.server.body("<non-existent@example.com>")
        self.assertEqual(cm.exception.response, "430 No Such Article Found")

    def test_body_file(self):
        f = io.BytesIO()
        resp, info = self.server.body(file=f)
        self.assertEqual(resp, "222 3000237 <45223423@example.com>")
        art_num, message_id, lines = info
        self.assertEqual(art_num, 3000237)
        self.assertEqual(message_id, "<45223423@example.com>")
        self.assertEqual(lines, [])
        data = f.getvalue()
        self.assertFalse(data.startswith(
            b'From: "Demo User" <nobody@example.net>\r\n'
            b'Subject: I am just a test article\r\n'
            ), ascii(data))
        self.assertTrue(data.endswith(
            b'This is just a test article.\r\n'
            b'.Here is a dot-starting line.\r\n'
            b'\r\n'
            b'-- Signed by Andr\xc3\xa9.\r\n'
            ), ascii(data))

    def check_over_xover_resp(self, resp, overviews):
        self.assertTrue(resp.startswith("224 "), resp)
        self.assertEqual(len(overviews), 3)
        art_num, over = overviews[0]
        self.assertEqual(art_num, 57)
        self.assertEqual(over, {
            "from": "Doug Hellmann <doug.hellmann-Re5JQEeQqe8AvxtiuMwx3w@public.gmane.org>",
            "subject": "Re: ANN: New Plone book with strong Python (and Zope) themes throughout",
            "date": "Sat, 19 Jun 2010 18:04:08 -0400",
            "message-id": "<4FD05F05-F98B-44DC-8111-C6009C925F0C@gmail.com>",
            "references": "<hvalf7$ort$1@dough.gmane.org>",
            ":bytes": "7103",
            ":lines": "16",
            "xref": "news.gmane.io gmane.comp.python.authors:57"
            })
        art_num, over = overviews[1]
        self.assertEqual(over["xref"], None)
        art_num, over = overviews[2]
        self.assertEqual(over["subject"],
                         "Re: Message d'erreur incompréhensible (par moi)")

    def test_xover(self):
        resp, overviews = self.server.xover(57, 59)
        self.check_over_xover_resp(resp, overviews)

    def test_over(self):
        # In NNTP "v1", this will fallback on XOVER
        resp, overviews = self.server.over((57, 59))
        self.check_over_xover_resp(resp, overviews)

    sample_post = (
        b'From: "Demo User" <nobody@example.net>\r\n'
        b'Subject: I am just a test article\r\n'
        b'Content-Type: text/plain; charset=UTF-8; format=flowed\r\n'
        b'Message-ID: <i.am.an.article.you.will.want@example.com>\r\n'
        b'\r\n'
        b'This is just a test article.\r\n'
        b'.Here is a dot-starting line.\r\n'
        b'\r\n'
        b'-- Signed by Andr\xc3\xa9.\r\n'
    )

    def _check_posted_body(self):
        # Check the raw body as received by the server
        lines = self.handler.posted_body
        # One additional line for the "." terminator
        self.assertEqual(len(lines), 10)
        self.assertEqual(lines[-1], b'.\r\n')
        self.assertEqual(lines[-2], b'-- Signed by Andr\xc3\xa9.\r\n')
        self.assertEqual(lines[-3], b'\r\n')
        self.assertEqual(lines[-4], b'..Here is a dot-starting line.\r\n')
        self.assertEqual(lines[0], b'From: "Demo User" <nobody@example.net>\r\n')

    def _check_post_ihave_sub(self, func, *args, file_factory):
        # First the prepared post with CRLF endings
        post = self.sample_post
        func_args = args + (file_factory(post),)
        self.handler.posted_body = None
        resp = func(*func_args)
        self._check_posted_body()
        # Then the same post with "normal" line endings - they should be
        # converted by NNTP.post and NNTP.ihave.
        post = self.sample_post.replace(b"\r\n", b"\n")
        func_args = args + (file_factory(post),)
        self.handler.posted_body = None
        resp = func(*func_args)
        self._check_posted_body()
        return resp

    def check_post_ihave(self, func, success_resp, *args):
        # With a bytes object
        resp = self._check_post_ihave_sub(func, *args, file_factory=bytes)
        self.assertEqual(resp, success_resp)
        # With a bytearray object
        resp = self._check_post_ihave_sub(func, *args, file_factory=bytearray)
        self.assertEqual(resp, success_resp)
        # With a file object
        resp = self._check_post_ihave_sub(func, *args, file_factory=io.BytesIO)
        self.assertEqual(resp, success_resp)
        # With an iterable of terminated lines
        def iterlines(b):
            return iter(b.splitlines(keepends=True))
        resp = self._check_post_ihave_sub(func, *args, file_factory=iterlines)
        self.assertEqual(resp, success_resp)
        # With an iterable of non-terminated lines
        def iterlines(b):
            return iter(b.splitlines(keepends=False))
        resp = self._check_post_ihave_sub(func, *args, file_factory=iterlines)
        self.assertEqual(resp, success_resp)

    def test_post(self):
        self.check_post_ihave(self.server.post, "240 Article received OK")
        self.handler.allow_posting = False
        with self.assertRaises(nntplib.NNTPTemporaryError) as cm:
            self.server.post(self.sample_post)
        self.assertEqual(cm.exception.response,
                         "440 Posting not permitted")

    def test_ihave(self):
        self.check_post_ihave(self.server.ihave, "235 Article transferred OK",
                              "<i.am.an.article.you.will.want@example.com>")
        with self.assertRaises(nntplib.NNTPTemporaryError) as cm:
            self.server.ihave("<another.message.id>", self.sample_post)
        self.assertEqual(cm.exception.response,
                         "435 Article not wanted")

    def test_too_long_lines(self):
        dt = datetime.datetime(2010, 1, 1, 9, 0, 0)
        self.assertRaises(nntplib.NNTPDataError,
                          self.server.newnews, "comp.lang.python", dt)


class NNTPv1Tests(NNTPv1v2TestsMixin, MockedNNTPTestsMixin, unittest.TestCase):
    """Tests an NNTP v1 server (no capabilities)."""

    nntp_version = 1
    handler_class = NNTPv1Handler

    def test_caps(self):
        caps = self.server.getcapabilities()
        self.assertEqual(caps, {})
        self.assertEqual(self.server.nntp_version, 1)
        self.assertEqual(self.server.nntp_implementation, None)


class NNTPv2Tests(NNTPv1v2TestsMixin, MockedNNTPTestsMixin, unittest.TestCase):
    """Tests an NNTP v2 server (with capabilities)."""

    nntp_version = 2
    handler_class = NNTPv2Handler

    def test_caps(self):
        caps = self.server.getcapabilities()
        self.assertEqual(caps, {
            'VERSION': ['2', '3'],
            'IMPLEMENTATION': ['INN', '2.5.1'],
            'AUTHINFO': ['USER'],
            'HDR': [],
            'LIST': ['ACTIVE', 'ACTIVE.TIMES', 'DISTRIB.PATS',
                     'HEADERS', 'NEWSGROUPS', 'OVERVIEW.FMT'],
            'OVER': [],
            'POST': [],
            'READER': [],
            })
        self.assertEqual(self.server.nntp_version, 3)
        self.assertEqual(self.server.nntp_implementation, 'INN 2.5.1')


class CapsAfterLoginNNTPv2Tests(MockedNNTPTestsMixin, unittest.TestCase):
    """Tests a probably NNTP v2 server with capabilities only after login."""

    nntp_version = 2
    handler_class = CapsAfterLoginNNTPv2Handler

    def test_caps_only_after_login(self):
        self.assertEqual(self.server._caps, {})
        self.server.login('testuser', 'testpw')
        self.assertIn('VERSION', self.server._caps)


class SendReaderNNTPv2Tests(MockedNNTPWithReaderModeMixin,
        unittest.TestCase):
    """Same tests as for v2 but we tell NTTP to send MODE READER to a server
    that isn't in READER mode by default."""

    nntp_version = 2
    handler_class = ModeSwitchingNNTPv2Handler

    def test_we_are_in_reader_mode_after_connect(self):
        self.assertIn('READER', self.server._caps)


class MiscTests(unittest.TestCase):

    def test_decode_header(self):
        def gives(a, b):
            self.assertEqual(nntplib.decode_header(a), b)
        gives("" , "")
        gives("a plain header", "a plain header")
        gives(" with extra  spaces ", " with extra  spaces ")
        gives("=?ISO-8859-15?Q?D=E9buter_en_Python?=", "Débuter en Python")
        gives("=?utf-8?q?Re=3A_=5Bsqlite=5D_probl=C3=A8me_avec_ORDER_BY_sur_des_cha?="
              " =?utf-8?q?=C3=AEnes_de_caract=C3=A8res_accentu=C3=A9es?=",
              "Re: [sqlite] problème avec ORDER BY sur des chaînes de caractères accentuées")
        gives("Re: =?UTF-8?B?cHJvYmzDqG1lIGRlIG1hdHJpY2U=?=",
              "Re: problème de matrice")
        # A natively utf-8 header (found in the real world!)
        gives("Re: Message d'erreur incompréhensible (par moi)",
              "Re: Message d'erreur incompréhensible (par moi)")

    def test_parse_overview_fmt(self):
        # The minimal (default) response
        lines = ["Subject:", "From:", "Date:", "Message-ID:",
                 "References:", ":bytes", ":lines"]
        self.assertEqual(nntplib._parse_overview_fmt(lines),
            ["subject", "from", "date", "message-id", "references",
             ":bytes", ":lines"])
        # The minimal response using alternative names
        lines = ["Subject:", "From:", "Date:", "Message-ID:",
                 "References:", "Bytes:", "Lines:"]
        self.assertEqual(nntplib._parse_overview_fmt(lines),
            ["subject", "from", "date", "message-id", "references",
             ":bytes", ":lines"])
        # Variations in casing
        lines = ["subject:", "FROM:", "DaTe:", "message-ID:",
                 "References:", "BYTES:", "Lines:"]
        self.assertEqual(nntplib._parse_overview_fmt(lines),
            ["subject", "from", "date", "message-id", "references",
             ":bytes", ":lines"])
        # First example from RFC 3977
        lines = ["Subject:", "From:", "Date:", "Message-ID:",
                 "References:", ":bytes", ":lines", "Xref:full",
                 "Distribution:full"]
        self.assertEqual(nntplib._parse_overview_fmt(lines),
            ["subject", "from", "date", "message-id", "references",
             ":bytes", ":lines", "xref", "distribution"])
        # Second example from RFC 3977
        lines = ["Subject:", "From:", "Date:", "Message-ID:",
                 "References:", "Bytes:", "Lines:", "Xref:FULL",
                 "Distribution:FULL"]
        self.assertEqual(nntplib._parse_overview_fmt(lines),
            ["subject", "from", "date", "message-id", "references",
             ":bytes", ":lines", "xref", "distribution"])
        # A classic response from INN
        lines = ["Subject:", "From:", "Date:", "Message-ID:",
                 "References:", "Bytes:", "Lines:", "Xref:full"]
        self.assertEqual(nntplib._parse_overview_fmt(lines),
            ["subject", "from", "date", "message-id", "references",
             ":bytes", ":lines", "xref"])

    def test_parse_overview(self):
        fmt = nntplib._DEFAULT_OVERVIEW_FMT + ["xref"]
        # First example from RFC 3977
        lines = [
            '3000234\tI am just a test article\t"Demo User" '
            '<nobody@example.com>\t6 Oct 1998 04:38:40 -0500\t'
            '<45223423@example.com>\t<45454@example.net>\t1234\t'
            '17\tXref: news.example.com misc.test:3000363',
        ]
        overview = nntplib._parse_overview(lines, fmt)
        (art_num, fields), = overview
        self.assertEqual(art_num, 3000234)
        self.assertEqual(fields, {
            'subject': 'I am just a test article',
            'from': '"Demo User" <nobody@example.com>',
            'date': '6 Oct 1998 04:38:40 -0500',
            'message-id': '<45223423@example.com>',
            'references': '<45454@example.net>',
            ':bytes': '1234',
            ':lines': '17',
            'xref': 'news.example.com misc.test:3000363',
        })
        # Second example; here the "Xref" field is totally absent (including
        # the header name) and comes out as None
        lines = [
            '3000234\tI am just a test article\t"Demo User" '
            '<nobody@example.com>\t6 Oct 1998 04:38:40 -0500\t'
            '<45223423@example.com>\t<45454@example.net>\t1234\t'
            '17\t\t',
        ]
        overview = nntplib._parse_overview(lines, fmt)
        (art_num, fields), = overview
        self.assertEqual(fields['xref'], None)
        # Third example; the "Xref" is an empty string, while "references"
        # is a single space.
        lines = [
            '3000234\tI am just a test article\t"Demo User" '
            '<nobody@example.com>\t6 Oct 1998 04:38:40 -0500\t'
            '<45223423@example.com>\t \t1234\t'
            '17\tXref: \t',
        ]
        overview = nntplib._parse_overview(lines, fmt)
        (art_num, fields), = overview
        self.assertEqual(fields['references'], ' ')
        self.assertEqual(fields['xref'], '')

    def test_parse_datetime(self):
        def gives(a, b, *c):
            self.assertEqual(nntplib._parse_datetime(a, b),
                             datetime.datetime(*c))
        # Output of DATE command
        gives("19990623135624", None, 1999, 6, 23, 13, 56, 24)
        # Variations
        gives("19990623", "135624", 1999, 6, 23, 13, 56, 24)
        gives("990623", "135624", 1999, 6, 23, 13, 56, 24)
        gives("090623", "135624", 2009, 6, 23, 13, 56, 24)

    def test_unparse_datetime(self):
        # Test non-legacy mode
        # 1) with a datetime
        def gives(y, M, d, h, m, s, date_str, time_str):
            dt = datetime.datetime(y, M, d, h, m, s)
            self.assertEqual(nntplib._unparse_datetime(dt),
                             (date_str, time_str))
            self.assertEqual(nntplib._unparse_datetime(dt, False),
                             (date_str, time_str))
        gives(1999, 6, 23, 13, 56, 24, "19990623", "135624")
        gives(2000, 6, 23, 13, 56, 24, "20000623", "135624")
        gives(2010, 6, 5, 1, 2, 3, "20100605", "010203")
        # 2) with a date
        def gives(y, M, d, date_str, time_str):
            dt = datetime.date(y, M, d)
            self.assertEqual(nntplib._unparse_datetime(dt),
                             (date_str, time_str))
            self.assertEqual(nntplib._unparse_datetime(dt, False),
                             (date_str, time_str))
        gives(1999, 6, 23, "19990623", "000000")
        gives(2000, 6, 23, "20000623", "000000")
        gives(2010, 6, 5, "20100605", "000000")

    def test_unparse_datetime_legacy(self):
        # Test legacy mode (RFC 977)
        # 1) with a datetime
        def gives(y, M, d, h, m, s, date_str, time_str):
            dt = datetime.datetime(y, M, d, h, m, s)
            self.assertEqual(nntplib._unparse_datetime(dt, True),
                             (date_str, time_str))
        gives(1999, 6, 23, 13, 56, 24, "990623", "135624")
        gives(2000, 6, 23, 13, 56, 24, "000623", "135624")
        gives(2010, 6, 5, 1, 2, 3, "100605", "010203")
        # 2) with a date
        def gives(y, M, d, date_str, time_str):
            dt = datetime.date(y, M, d)
            self.assertEqual(nntplib._unparse_datetime(dt, True),
                             (date_str, time_str))
        gives(1999, 6, 23, "990623", "000000")
        gives(2000, 6, 23, "000623", "000000")
        gives(2010, 6, 5, "100605", "000000")

    @unittest.skipUnless(ssl, 'requires SSL support')
    def test_ssl_support(self):
        self.assertTrue(hasattr(nntplib, 'NNTP_SSL'))


class PublicAPITests(unittest.TestCase):
    """Ensures that the correct values are exposed in the public API."""

    def test_module_all_attribute(self):
        self.assertTrue(hasattr(nntplib, '__all__'))
        target_api = ['NNTP', 'NNTPError', 'NNTPReplyError',
                      'NNTPTemporaryError', 'NNTPPermanentError',
                      'NNTPProtocolError', 'NNTPDataError', 'decode_header']
        if ssl is not None:
            target_api.append('NNTP_SSL')
        self.assertEqual(set(nntplib.__all__), set(target_api))

class MockSocketTests(unittest.TestCase):
    """Tests involving a mock socket object

    Used where the _NNTPServerIO file object is not enough."""

    nntp_class = nntplib.NNTP

    def check_constructor_error_conditions(
            self, handler_class,
            expected_error_type, expected_error_msg,
            login=None, password=None):

        class mock_socket_module:
            def create_connection(address, timeout):
                return MockSocket()

        class MockSocket:
            def close(self):
                nonlocal socket_closed
                socket_closed = True

            def makefile(socket, mode):
                handler = handler_class()
                _, file = make_mock_file(handler)
                files.append(file)
                return file

        socket_closed = False
        files = []
        with patch('nntplib.socket', mock_socket_module), \
             self.assertRaisesRegex(expected_error_type, expected_error_msg):
            self.nntp_class('dummy', user=login, password=password)
        self.assertTrue(socket_closed)
        for f in files:
            self.assertTrue(f.closed)

    def test_bad_welcome(self):
        #Test a bad welcome message
        class Handler(NNTPv1Handler):
            welcome = 'Bad Welcome'
        self.check_constructor_error_conditions(
            Handler, nntplib.NNTPProtocolError, Handler.welcome)

    def test_service_temporarily_unavailable(self):
        #Test service temporarily unavailable
        class Handler(NNTPv1Handler):
            welcome = '400 Service temporarily unavailable'
        self.check_constructor_error_conditions(
            Handler, nntplib.NNTPTemporaryError, Handler.welcome)

    def test_service_permanently_unavailable(self):
        #Test service permanently unavailable
        class Handler(NNTPv1Handler):
            welcome = '502 Service permanently unavailable'
        self.check_constructor_error_conditions(
            Handler, nntplib.NNTPPermanentError, Handler.welcome)

    def test_bad_capabilities(self):
        #Test a bad capabilities response
        class Handler(NNTPv1Handler):
            def handle_CAPABILITIES(self):
                self.push_lit(capabilities_response)
        capabilities_response = '201 bad capability'
        self.check_constructor_error_conditions(
            Handler, nntplib.NNTPReplyError, capabilities_response)

    def test_login_aborted(self):
        #Test a bad authinfo response
        login = 't@e.com'
        password = 'python'
        class Handler(NNTPv1Handler):
            def handle_AUTHINFO(self, *args):
                self.push_lit(authinfo_response)
        authinfo_response = '503 Mechanism not recognized'
        self.check_constructor_error_conditions(
            Handler, nntplib.NNTPPermanentError, authinfo_response,
            login, password)

class bypass_context:
    """Bypass encryption and actual SSL module"""
    def wrap_socket(sock, **args):
        return sock

@unittest.skipUnless(ssl, 'requires SSL support')
class MockSslTests(MockSocketTests):
    @staticmethod
    def nntp_class(*pos, **kw):
        return nntplib.NNTP_SSL(*pos, ssl_context=bypass_context, **kw)


class LocalServerTests(unittest.TestCase):
    def setUp(self):
        sock = socket.socket()
        port = socket_helper.bind_port(sock)
        sock.listen()
        self.background = threading.Thread(
            target=self.run_server, args=(sock,))
        self.background.start()
        self.addCleanup(self.background.join)

        self.nntp = self.enterContext(NNTP(socket_helper.HOST, port, usenetrc=False))

    def run_server(self, sock):
        # Could be generalized to handle more commands in separate methods
        with sock:
            [client, _] = sock.accept()
        with contextlib.ExitStack() as cleanup:
            cleanup.enter_context(client)
            reader = cleanup.enter_context(client.makefile('rb'))
            client.sendall(b'200 Server ready\r\n')
            while True:
                cmd = reader.readline()
                if cmd == b'CAPABILITIES\r\n':
                    client.sendall(
                        b'101 Capability list:\r\n'
                        b'VERSION 2\r\n'
                        b'STARTTLS\r\n'
                        b'.\r\n'
                    )
                elif cmd == b'STARTTLS\r\n':
                    reader.close()
                    client.sendall(b'382 Begin TLS negotiation now\r\n')
                    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                    context.load_cert_chain(certfile)
                    client = context.wrap_socket(
                        client, server_side=True)
                    cleanup.enter_context(client)
                    reader = cleanup.enter_context(client.makefile('rb'))
                elif cmd == b'QUIT\r\n':
                    client.sendall(b'205 Bye!\r\n')
                    break
                else:
                    raise ValueError('Unexpected command {!r}'.format(cmd))

    @unittest.skipUnless(ssl, 'requires SSL support')
    def test_starttls(self):
        file = self.nntp.file
        sock = self.nntp.sock
        self.nntp.starttls()
        # Check that the socket and internal pseudo-file really were
        # changed.
        self.assertNotEqual(file, self.nntp.file)
        self.assertNotEqual(sock, self.nntp.sock)
        # Check that the new socket really is an SSL one
        self.assertIsInstance(self.nntp.sock, ssl.SSLSocket)
        # Check that trying starttls when it's already active fails.
        self.assertRaises(ValueError, self.nntp.starttls)


if __name__ == "__main__":
    unittest.main()
import inspect
import ntpath
import os
import sys
import unittest
import warnings
from test.support import cpython_only, os_helper
from test.support import TestFailed, is_emscripten
from test.support.os_helper import FakePath
from test import test_genericpath
from tempfile import TemporaryFile


try:
    import nt
except ImportError:
    # Most tests can complete without the nt module,
    # but for those that require it we import here.
    nt = None

try:
    ntpath._getfinalpathname
except AttributeError:
    HAVE_GETFINALPATHNAME = False
else:
    HAVE_GETFINALPATHNAME = True

try:
    import ctypes
except ImportError:
    HAVE_GETSHORTPATHNAME = False
else:
    HAVE_GETSHORTPATHNAME = True
    def _getshortpathname(path):
        GSPN = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
        GSPN.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        GSPN.restype = ctypes.c_uint32
        result_len = GSPN(path, None, 0)
        if not result_len:
            raise OSError("failed to get short path name 0x{:08X}"
                          .format(ctypes.get_last_error()))
        result = ctypes.create_unicode_buffer(result_len)
        result_len = GSPN(path, result, result_len)
        return result[:result_len]

def _norm(path):
    if isinstance(path, (bytes, str, os.PathLike)):
        return ntpath.normcase(os.fsdecode(path))
    elif hasattr(path, "__iter__"):
        return tuple(ntpath.normcase(os.fsdecode(p)) for p in path)
    return path


def tester(fn, wantResult):
    fn = fn.replace("\\", "\\\\")
    gotResult = eval(fn)
    if wantResult != gotResult and _norm(wantResult) != _norm(gotResult):
        raise TestFailed("%s should return: %s but returned: %s" \
              %(str(fn), str(wantResult), str(gotResult)))

    # then with bytes
    fn = fn.replace("('", "(b'")
    fn = fn.replace('("', '(b"')
    fn = fn.replace("['", "[b'")
    fn = fn.replace('["', '[b"')
    fn = fn.replace(", '", ", b'")
    fn = fn.replace(', "', ', b"')
    fn = os.fsencode(fn).decode('latin1')
    fn = fn.encode('ascii', 'backslashreplace').decode('ascii')
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        gotResult = eval(fn)
    if _norm(wantResult) != _norm(gotResult):
        raise TestFailed("%s should return: %s but returned: %s" \
              %(str(fn), str(wantResult), repr(gotResult)))


class NtpathTestCase(unittest.TestCase):
    def assertPathEqual(self, path1, path2):
        if path1 == path2 or _norm(path1) == _norm(path2):
            return
        self.assertEqual(path1, path2)

    def assertPathIn(self, path, pathset):
        self.assertIn(_norm(path), _norm(pathset))


class TestNtpath(NtpathTestCase):
    def test_splitext(self):
        tester('ntpath.splitext("foo.ext")', ('foo', '.ext'))
        tester('ntpath.splitext("/foo/foo.ext")', ('/foo/foo', '.ext'))
        tester('ntpath.splitext(".ext")', ('.ext', ''))
        tester('ntpath.splitext("\\foo.ext\\foo")', ('\\foo.ext\\foo', ''))
        tester('ntpath.splitext("foo.ext\\")', ('foo.ext\\', ''))
        tester('ntpath.splitext("")', ('', ''))
        tester('ntpath.splitext("foo.bar.ext")', ('foo.bar', '.ext'))
        tester('ntpath.splitext("xx/foo.bar.ext")', ('xx/foo.bar', '.ext'))
        tester('ntpath.splitext("xx\\foo.bar.ext")', ('xx\\foo.bar', '.ext'))
        tester('ntpath.splitext("c:a/b\\c.d")', ('c:a/b\\c', '.d'))

    def test_splitdrive(self):
        tester("ntpath.splitdrive('')", ('', ''))
        tester("ntpath.splitdrive('foo')", ('', 'foo'))
        tester("ntpath.splitdrive('foo\\bar')", ('', 'foo\\bar'))
        tester("ntpath.splitdrive('foo/bar')", ('', 'foo/bar'))
        tester("ntpath.splitdrive('\\')", ('', '\\'))
        tester("ntpath.splitdrive('/')", ('', '/'))
        tester("ntpath.splitdrive('\\foo\\bar')", ('', '\\foo\\bar'))
        tester("ntpath.splitdrive('/foo/bar')", ('', '/foo/bar'))
        tester('ntpath.splitdrive("c:foo\\bar")', ('c:', 'foo\\bar'))
        tester('ntpath.splitdrive("c:foo/bar")', ('c:', 'foo/bar'))
        tester('ntpath.splitdrive("c:\\foo\\bar")', ('c:', '\\foo\\bar'))
        tester('ntpath.splitdrive("c:/foo/bar")', ('c:', '/foo/bar'))
        tester("ntpath.splitdrive('\\\\')", ('\\\\', ''))
        tester("ntpath.splitdrive('//')", ('//', ''))
        tester('ntpath.splitdrive("\\\\conky\\mountpoint\\foo\\bar")',
               ('\\\\conky\\mountpoint', '\\foo\\bar'))
        tester('ntpath.splitdrive("//conky/mountpoint/foo/bar")',
               ('//conky/mountpoint', '/foo/bar'))
        tester('ntpath.splitdrive("\\\\?\\UNC\\server\\share\\dir")',
               ("\\\\?\\UNC\\server\\share", "\\dir"))
        tester('ntpath.splitdrive("//?/UNC/server/share/dir")',
               ("//?/UNC/server/share", "/dir"))

    def test_splitroot(self):
        tester("ntpath.splitroot('')", ('', '', ''))
        tester("ntpath.splitroot('foo')", ('', '', 'foo'))
        tester("ntpath.splitroot('foo\\bar')", ('', '', 'foo\\bar'))
        tester("ntpath.splitroot('foo/bar')", ('', '', 'foo/bar'))
        tester("ntpath.splitroot('\\')", ('', '\\', ''))
        tester("ntpath.splitroot('/')", ('', '/', ''))
        tester("ntpath.splitroot('\\foo\\bar')", ('', '\\', 'foo\\bar'))
        tester("ntpath.splitroot('/foo/bar')", ('', '/', 'foo/bar'))
        tester('ntpath.splitroot("c:foo\\bar")', ('c:', '', 'foo\\bar'))
        tester('ntpath.splitroot("c:foo/bar")', ('c:', '', 'foo/bar'))
        tester('ntpath.splitroot("c:\\foo\\bar")', ('c:', '\\', 'foo\\bar'))
        tester('ntpath.splitroot("c:/foo/bar")', ('c:', '/', 'foo/bar'))

        # Redundant slashes are not included in the root.
        tester("ntpath.splitroot('c:\\\\a')", ('c:', '\\', '\\a'))
        tester("ntpath.splitroot('c:\\\\\\a/b')", ('c:', '\\', '\\\\a/b'))

        # Mixed path separators.
        tester("ntpath.splitroot('c:/\\')", ('c:', '/', '\\'))
        tester("ntpath.splitroot('c:\\/')", ('c:', '\\', '/'))
        tester("ntpath.splitroot('/\\a/b\\/\\')", ('/\\a/b', '\\', '/\\'))
        tester("ntpath.splitroot('\\/a\\b/\\/')", ('\\/a\\b', '/', '\\/'))

        # UNC paths.
        tester("ntpath.splitroot('\\\\')", ('\\\\', '', ''))
        tester("ntpath.splitroot('//')", ('//', '', ''))
        tester('ntpath.splitroot("\\\\conky\\mountpoint\\foo\\bar")',
               ('\\\\conky\\mountpoint', '\\', 'foo\\bar'))
        tester('ntpath.splitroot("//conky/mountpoint/foo/bar")',
               ('//conky/mountpoint', '/', 'foo/bar'))
        tester('ntpath.splitroot("\\\\\\conky\\mountpoint\\foo\\bar")',
            ('\\\\\\conky', '\\', 'mountpoint\\foo\\bar'))
        tester('ntpath.splitroot("///conky/mountpoint/foo/bar")',
            ('///conky', '/', 'mountpoint/foo/bar'))
        tester('ntpath.splitroot("\\\\conky\\\\mountpoint\\foo\\bar")',
               ('\\\\conky\\', '\\', 'mountpoint\\foo\\bar'))
        tester('ntpath.splitroot("//conky//mountpoint/foo/bar")',
               ('//conky/', '/', 'mountpoint/foo/bar'))

        # Issue #19911: UNC part containing U+0130
        self.assertEqual(ntpath.splitroot('//conky/MOUNTPOİNT/foo/bar'),
                         ('//conky/MOUNTPOİNT', '/', 'foo/bar'))

        # gh-81790: support device namespace, including UNC drives.
        tester('ntpath.splitroot("//?/c:")', ("//?/c:", "", ""))
        tester('ntpath.splitroot("//?/c:/")', ("//?/c:", "/", ""))
        tester('ntpath.splitroot("//?/c:/dir")', ("//?/c:", "/", "dir"))
        tester('ntpath.splitroot("//?/UNC")', ("//?/UNC", "", ""))
        tester('ntpath.splitroot("//?/UNC/")', ("//?/UNC/", "", ""))
        tester('ntpath.splitroot("//?/UNC/server/")', ("//?/UNC/server/", "", ""))
        tester('ntpath.splitroot("//?/UNC/server/share")', ("//?/UNC/server/share", "", ""))
        tester('ntpath.splitroot("//?/UNC/server/share/dir")', ("//?/UNC/server/share", "/", "dir"))
        tester('ntpath.splitroot("//?/VOLUME{00000000-0000-0000-0000-000000000000}/spam")',
               ('//?/VOLUME{00000000-0000-0000-0000-000000000000}', '/', 'spam'))
        tester('ntpath.splitroot("//?/BootPartition/")', ("//?/BootPartition", "/", ""))

        tester('ntpath.splitroot("\\\\?\\c:")', ("\\\\?\\c:", "", ""))
        tester('ntpath.splitroot("\\\\?\\c:\\")', ("\\\\?\\c:", "\\", ""))
        tester('ntpath.splitroot("\\\\?\\c:\\dir")', ("\\\\?\\c:", "\\", "dir"))
        tester('ntpath.splitroot("\\\\?\\UNC")', ("\\\\?\\UNC", "", ""))
        tester('ntpath.splitroot("\\\\?\\UNC\\")', ("\\\\?\\UNC\\", "", ""))
        tester('ntpath.splitroot("\\\\?\\UNC\\server\\")', ("\\\\?\\UNC\\server\\", "", ""))
        tester('ntpath.splitroot("\\\\?\\UNC\\server\\share")',
               ("\\\\?\\UNC\\server\\share", "", ""))
        tester('ntpath.splitroot("\\\\?\\UNC\\server\\share\\dir")',
               ("\\\\?\\UNC\\server\\share", "\\", "dir"))
        tester('ntpath.splitroot("\\\\?\\VOLUME{00000000-0000-0000-0000-000000000000}\\spam")',
               ('\\\\?\\VOLUME{00000000-0000-0000-0000-000000000000}', '\\', 'spam'))
        tester('ntpath.splitroot("\\\\?\\BootPartition\\")', ("\\\\?\\BootPartition", "\\", ""))

        # gh-96290: support partial/invalid UNC drives
        tester('ntpath.splitroot("//")', ("//", "", ""))  # empty server & missing share
        tester('ntpath.splitroot("///")', ("///", "", ""))  # empty server & empty share
        tester('ntpath.splitroot("///y")', ("///y", "", ""))  # empty server & non-empty share
        tester('ntpath.splitroot("//x")', ("//x", "", ""))  # non-empty server & missing share
        tester('ntpath.splitroot("//x/")', ("//x/", "", ""))  # non-empty server & empty share

    def test_split(self):
        tester('ntpath.split("c:\\foo\\bar")', ('c:\\foo', 'bar'))
        tester('ntpath.split("\\\\conky\\mountpoint\\foo\\bar")',
               ('\\\\conky\\mountpoint\\foo', 'bar'))

        tester('ntpath.split("c:\\")', ('c:\\', ''))
        tester('ntpath.split("\\\\conky\\mountpoint\\")',
               ('\\\\conky\\mountpoint\\', ''))

        tester('ntpath.split("c:/")', ('c:/', ''))
        tester('ntpath.split("//conky/mountpoint/")', ('//conky/mountpoint/', ''))

    def test_isabs(self):
        tester('ntpath.isabs("c:\\")', 1)
        tester('ntpath.isabs("\\\\conky\\mountpoint\\")', 1)
        tester('ntpath.isabs("\\foo")', 1)
        tester('ntpath.isabs("\\foo\\bar")', 1)

        # gh-96290: normal UNC paths and device paths without trailing backslashes
        tester('ntpath.isabs("\\\\conky\\mountpoint")', 1)
        tester('ntpath.isabs("\\\\.\\C:")', 1)

    def test_commonprefix(self):
        tester('ntpath.commonprefix(["/home/swenson/spam", "/home/swen/spam"])',
               "/home/swen")
        tester('ntpath.commonprefix(["\\home\\swen\\spam", "\\home\\swen\\eggs"])',
               "\\home\\swen\\")
        tester('ntpath.commonprefix(["/home/swen/spam", "/home/swen/spam"])',
               "/home/swen/spam")

    def test_join(self):
        tester('ntpath.join("")', '')
        tester('ntpath.join("", "", "")', '')
        tester('ntpath.join("a")', 'a')
        tester('ntpath.join("/a")', '/a')
        tester('ntpath.join("\\a")', '\\a')
        tester('ntpath.join("a:")', 'a:')
        tester('ntpath.join("a:", "\\b")', 'a:\\b')
        tester('ntpath.join("a", "\\b")', '\\b')
        tester('ntpath.join("a", "b", "c")', 'a\\b\\c')
        tester('ntpath.join("a\\", "b", "c")', 'a\\b\\c')
        tester('ntpath.join("a", "b\\", "c")', 'a\\b\\c')
        tester('ntpath.join("a", "b", "\\c")', '\\c')
        tester('ntpath.join("d:\\", "\\pleep")', 'd:\\pleep')
        tester('ntpath.join("d:\\", "a", "b")', 'd:\\a\\b')

        tester("ntpath.join('', 'a')", 'a')
        tester("ntpath.join('', '', '', '', 'a')", 'a')
        tester("ntpath.join('a', '')", 'a\\')
        tester("ntpath.join('a', '', '', '', '')", 'a\\')
        tester("ntpath.join('a\\', '')", 'a\\')
        tester("ntpath.join('a\\', '', '', '', '')", 'a\\')
        tester("ntpath.join('a/', '')", 'a/')

        tester("ntpath.join('a/b', 'x/y')", 'a/b\\x/y')
        tester("ntpath.join('/a/b', 'x/y')", '/a/b\\x/y')
        tester("ntpath.join('/a/b/', 'x/y')", '/a/b/x/y')
        tester("ntpath.join('c:', 'x/y')", 'c:x/y')
        tester("ntpath.join('c:a/b', 'x/y')", 'c:a/b\\x/y')
        tester("ntpath.join('c:a/b/', 'x/y')", 'c:a/b/x/y')
        tester("ntpath.join('c:/', 'x/y')", 'c:/x/y')
        tester("ntpath.join('c:/a/b', 'x/y')", 'c:/a/b\\x/y')
        tester("ntpath.join('c:/a/b/', 'x/y')", 'c:/a/b/x/y')
        tester("ntpath.join('//computer/share', 'x/y')", '//computer/share\\x/y')
        tester("ntpath.join('//computer/share/', 'x/y')", '//computer/share/x/y')
        tester("ntpath.join('//computer/share/a/b', 'x/y')", '//computer/share/a/b\\x/y')

        tester("ntpath.join('a/b', '/x/y')", '/x/y')
        tester("ntpath.join('/a/b', '/x/y')", '/x/y')
        tester("ntpath.join('c:', '/x/y')", 'c:/x/y')
        tester("ntpath.join('c:a/b', '/x/y')", 'c:/x/y')
        tester("ntpath.join('c:/', '/x/y')", 'c:/x/y')
        tester("ntpath.join('c:/a/b', '/x/y')", 'c:/x/y')
        tester("ntpath.join('//computer/share', '/x/y')", '//computer/share/x/y')
        tester("ntpath.join('//computer/share/', '/x/y')", '//computer/share/x/y')
        tester("ntpath.join('//computer/share/a', '/x/y')", '//computer/share/x/y')

        tester("ntpath.join('c:', 'C:x/y')", 'C:x/y')
        tester("ntpath.join('c:a/b', 'C:x/y')", 'C:a/b\\x/y')
        tester("ntpath.join('c:/', 'C:x/y')", 'C:/x/y')
        tester("ntpath.join('c:/a/b', 'C:x/y')", 'C:/a/b\\x/y')

        for x in ('', 'a/b', '/a/b', 'c:', 'c:a/b', 'c:/', 'c:/a/b',
                  '//computer/share', '//computer/share/', '//computer/share/a/b'):
            for y in ('d:', 'd:x/y', 'd:/', 'd:/x/y',
                      '//machine/common', '//machine/common/', '//machine/common/x/y'):
                tester("ntpath.join(%r, %r)" % (x, y), y)

        tester("ntpath.join('\\\\computer\\share\\', 'a', 'b')", '\\\\computer\\share\\a\\b')
        tester("ntpath.join('\\\\computer\\share', 'a', 'b')", '\\\\computer\\share\\a\\b')
        tester("ntpath.join('\\\\computer\\share', 'a\\b')", '\\\\computer\\share\\a\\b')
        tester("ntpath.join('//computer/share/', 'a', 'b')", '//computer/share/a\\b')
        tester("ntpath.join('//computer/share', 'a', 'b')", '//computer/share\\a\\b')
        tester("ntpath.join('//computer/share', 'a/b')", '//computer/share\\a/b')

    def test_normpath(self):
        tester("ntpath.normpath('A//////././//.//B')", r'A\B')
        tester("ntpath.normpath('A/./B')", r'A\B')
        tester("ntpath.normpath('A/foo/../B')", r'A\B')
        tester("ntpath.normpath('C:A//B')", r'C:A\B')
        tester("ntpath.normpath('D:A/./B')", r'D:A\B')
        tester("ntpath.normpath('e:A/foo/../B')", r'e:A\B')

        tester("ntpath.normpath('C:///A//B')", r'C:\A\B')
        tester("ntpath.normpath('D:///A/./B')", r'D:\A\B')
        tester("ntpath.normpath('e:///A/foo/../B')", r'e:\A\B')

        tester("ntpath.normpath('..')", r'..')
        tester("ntpath.normpath('.')", r'.')
        tester("ntpath.normpath('')", r'.')
        tester("ntpath.normpath('/')", '\\')
        tester("ntpath.normpath('c:/')", 'c:\\')
        tester("ntpath.normpath('/../.././..')", '\\')
        tester("ntpath.normpath('c:/../../..')", 'c:\\')
        tester("ntpath.normpath('../.././..')", r'..\..\..')
        tester("ntpath.normpath('K:../.././..')", r'K:..\..\..')
        tester("ntpath.normpath('C:////a/b')", r'C:\a\b')
        tester("ntpath.normpath('//machine/share//a/b')", r'\\machine\share\a\b')

        tester("ntpath.normpath('\\\\.\\NUL')", r'\\.\NUL')
        tester("ntpath.normpath('\\\\?\\D:/XY\\Z')", r'\\?\D:/XY\Z')
        tester("ntpath.normpath('handbook/../../Tests/image.png')", r'..\Tests\image.png')
        tester("ntpath.normpath('handbook/../../../Tests/image.png')", r'..\..\Tests\image.png')
        tester("ntpath.normpath('handbook///../a/.././../b/c')", r'..\b\c')
        tester("ntpath.normpath('handbook/a/../..///../../b/c')", r'..\..\b\c')

        tester("ntpath.normpath('//server/share/..')" ,    '\\\\server\\share\\')
        tester("ntpath.normpath('//server/share/../')" ,   '\\\\server\\share\\')
        tester("ntpath.normpath('//server/share/../..')",  '\\\\server\\share\\')
        tester("ntpath.normpath('//server/share/../../')", '\\\\server\\share\\')

        # gh-96290: don't normalize partial/invalid UNC drives as rooted paths.
        tester("ntpath.normpath('\\\\foo\\\\')", '\\\\foo\\\\')
        tester("ntpath.normpath('\\\\foo\\')", '\\\\foo\\')
        tester("ntpath.normpath('\\\\foo')", '\\\\foo')
        tester("ntpath.normpath('\\\\')", '\\\\')

    def test_realpath_curdir(self):
        expected = ntpath.normpath(os.getcwd())
        tester("ntpath.realpath('.')", expected)
        tester("ntpath.realpath('./.')", expected)
        tester("ntpath.realpath('/'.join(['.'] * 100))", expected)
        tester("ntpath.realpath('.\\.')", expected)
        tester("ntpath.realpath('\\'.join(['.'] * 100))", expected)

    def test_realpath_pardir(self):
        expected = ntpath.normpath(os.getcwd())
        tester("ntpath.realpath('..')", ntpath.dirname(expected))
        tester("ntpath.realpath('../..')",
               ntpath.dirname(ntpath.dirname(expected)))
        tester("ntpath.realpath('/'.join(['..'] * 50))",
               ntpath.splitdrive(expected)[0] + '\\')
        tester("ntpath.realpath('..\\..')",
               ntpath.dirname(ntpath.dirname(expected)))
        tester("ntpath.realpath('\\'.join(['..'] * 50))",
               ntpath.splitdrive(expected)[0] + '\\')

    @os_helper.skip_unless_symlink
    @unittest.skipUnless(HAVE_GETFINALPATHNAME, 'need _getfinalpathname')
    def test_realpath_basic(self):
        ABSTFN = ntpath.abspath(os_helper.TESTFN)
        open(ABSTFN, "wb").close()
        self.addCleanup(os_helper.unlink, ABSTFN)
        self.addCleanup(os_helper.unlink, ABSTFN + "1")

        os.symlink(ABSTFN, ABSTFN + "1")
        self.assertPathEqual(ntpath.realpath(ABSTFN + "1"), ABSTFN)
        self.assertPathEqual(ntpath.realpath(os.fsencode(ABSTFN + "1")),
                         os.fsencode(ABSTFN))

    @os_helper.skip_unless_symlink
    @unittest.skipUnless(HAVE_GETFINALPATHNAME, 'need _getfinalpathname')
    def test_realpath_strict(self):
        # Bug #43757: raise FileNotFoundError in strict mode if we encounter
        # a path that does not exist.
        ABSTFN = ntpath.abspath(os_helper.TESTFN)
        os.symlink(ABSTFN + "1", ABSTFN)
        self.addCleanup(os_helper.unlink, ABSTFN)
        self.assertRaises(FileNotFoundError, ntpath.realpath, ABSTFN, strict=True)
        self.assertRaises(FileNotFoundError, ntpath.realpath, ABSTFN + "2", strict=True)

    @os_helper.skip_unless_symlink
    @unittest.skipUnless(HAVE_GETFINALPATHNAME, 'need _getfinalpathname')
    def test_realpath_relative(self):
        ABSTFN = ntpath.abspath(os_helper.TESTFN)
        open(ABSTFN, "wb").close()
        self.addCleanup(os_helper.unlink, ABSTFN)
        self.addCleanup(os_helper.unlink, ABSTFN + "1")

        os.symlink(ABSTFN, ntpath.relpath(ABSTFN + "1"))
        self.assertPathEqual(ntpath.realpath(ABSTFN + "1"), ABSTFN)

    @os_helper.skip_unless_symlink
    @unittest.skipUnless(HAVE_GETFINALPATHNAME, 'need _getfinalpathname')
    def test_realpath_broken_symlinks(self):
        ABSTFN = ntpath.abspath(os_helper.TESTFN)
        os.mkdir(ABSTFN)
        self.addCleanup(os_helper.rmtree, ABSTFN)

        with os_helper.change_cwd(ABSTFN):
            os.mkdir("subdir")
            os.chdir("subdir")
            os.symlink(".", "recursive")
            os.symlink("..", "parent")
            os.chdir("..")
            os.symlink(".", "self")
            os.symlink("missing", "broken")
            os.symlink(r"broken\bar", "broken1")
            os.symlink(r"self\self\broken", "broken2")
            os.symlink(r"subdir\parent\subdir\parent\broken", "broken3")
            os.symlink(ABSTFN + r"\broken", "broken4")
            os.symlink(r"recursive\..\broken", "broken5")

            self.assertPathEqual(ntpath.realpath("broken"),
                                 ABSTFN + r"\missing")
            self.assertPathEqual(ntpath.realpath(r"broken\foo"),
                                 ABSTFN + r"\missing\foo")
            # bpo-38453: We no longer recursively resolve segments of relative
            # symlinks that the OS cannot resolve.
            self.assertPathEqual(ntpath.realpath(r"broken1"),
                                 ABSTFN + r"\broken\bar")
            self.assertPathEqual(ntpath.realpath(r"broken1\baz"),
                                 ABSTFN + r"\broken\bar\baz")
            self.assertPathEqual(ntpath.realpath("broken2"),
                                 ABSTFN + r"\self\self\missing")
            self.assertPathEqual(ntpath.realpath("broken3"),
                                 ABSTFN + r"\subdir\parent\subdir\parent\missing")
            self.assertPathEqual(ntpath.realpath("broken4"),
                                 ABSTFN + r"\missing")
            self.assertPathEqual(ntpath.realpath("broken5"),
                                 ABSTFN + r"\missing")

            self.assertPathEqual(ntpath.realpath(b"broken"),
                                 os.fsencode(ABSTFN + r"\missing"))
            self.assertPathEqual(ntpath.realpath(rb"broken\foo"),
                                 os.fsencode(ABSTFN + r"\missing\foo"))
            self.assertPathEqual(ntpath.realpath(rb"broken1"),
                                 os.fsencode(ABSTFN + r"\broken\bar"))
            self.assertPathEqual(ntpath.realpath(rb"broken1\baz"),
                                 os.fsencode(ABSTFN + r"\broken\bar\baz"))
            self.assertPathEqual(ntpath.realpath(b"broken2"),
                                 os.fsencode(ABSTFN + r"\self\self\missing"))
            self.assertPathEqual(ntpath.realpath(rb"broken3"),
                                 os.fsencode(ABSTFN + r"\subdir\parent\subdir\parent\missing"))
            self.assertPathEqual(ntpath.realpath(b"broken4"),
                                 os.fsencode(ABSTFN + r"\missing"))
            self.assertPathEqual(ntpath.realpath(b"broken5"),
                                 os.fsencode(ABSTFN + r"\missing"))

    @os_helper.skip_unless_symlink
    @unittest.skipUnless(HAVE_GETFINALPATHNAME, 'need _getfinalpathname')
    def test_realpath_symlink_loops(self):
        # Symlink loops in non-strict mode are non-deterministic as to which
        # path is returned, but it will always be the fully resolved path of
        # one member of the cycle
        ABSTFN = ntpath.abspath(os_helper.TESTFN)
        self.addCleanup(os_helper.unlink, ABSTFN)
        self.addCleanup(os_helper.unlink, ABSTFN + "1")
        self.addCleanup(os_helper.unlink, ABSTFN + "2")
        self.addCleanup(os_helper.unlink, ABSTFN + "y")
        self.addCleanup(os_helper.unlink, ABSTFN + "c")
        self.addCleanup(os_helper.unlink, ABSTFN + "a")

        os.symlink(ABSTFN, ABSTFN)
        self.assertPathEqual(ntpath.realpath(ABSTFN), ABSTFN)

        os.symlink(ABSTFN + "1", ABSTFN + "2")
        os.symlink(ABSTFN + "2", ABSTFN + "1")
        expected = (ABSTFN + "1", ABSTFN + "2")
        self.assertPathIn(ntpath.realpath(ABSTFN + "1"), expected)
        self.assertPathIn(ntpath.realpath(ABSTFN + "2"), expected)

        self.assertPathIn(ntpath.realpath(ABSTFN + "1\\x"),
                          (ntpath.join(r, "x") for r in expected))
        self.assertPathEqual(ntpath.realpath(ABSTFN + "1\\.."),
                             ntpath.dirname(ABSTFN))
        self.assertPathEqual(ntpath.realpath(ABSTFN + "1\\..\\x"),
                             ntpath.dirname(ABSTFN) + "\\x")
        os.symlink(ABSTFN + "x", ABSTFN + "y")
        self.assertPathEqual(ntpath.realpath(ABSTFN + "1\\..\\"
                                             + ntpath.basename(ABSTFN) + "y"),
                             ABSTFN + "x")
        self.assertPathIn(ntpath.realpath(ABSTFN + "1\\..\\"
                                          + ntpath.basename(ABSTFN) + "1"),
                          expected)

        os.symlink(ntpath.basename(ABSTFN) + "a\\b", ABSTFN + "a")
        self.assertPathEqual(ntpath.realpath(ABSTFN + "a"), ABSTFN + "a")

        os.symlink("..\\" + ntpath.basename(ntpath.dirname(ABSTFN))
                   + "\\" + ntpath.basename(ABSTFN) + "c", ABSTFN + "c")
        self.assertPathEqual(ntpath.realpath(ABSTFN + "c"), ABSTFN + "c")

        # Test using relative path as well.
        self.assertPathEqual(ntpath.realpath(ntpath.basename(ABSTFN)), ABSTFN)

    @os_helper.skip_unless_symlink
    @unittest.skipUnless(HAVE_GETFINALPATHNAME, 'need _getfinalpathname')
    def test_realpath_symlink_loops_strict(self):
        # Symlink loops raise OSError in strict mode
        ABSTFN = ntpath.abspath(os_helper.TESTFN)
        self.addCleanup(os_helper.unlink, ABSTFN)
        self.addCleanup(os_helper.unlink, ABSTFN + "1")
        self.addCleanup(os_helper.unlink, ABSTFN + "2")
        self.addCleanup(os_helper.unlink, ABSTFN + "y")
        self.addCleanup(os_helper.unlink, ABSTFN + "c")
        self.addCleanup(os_helper.unlink, ABSTFN + "a")

        os.symlink(ABSTFN, ABSTFN)
        self.assertRaises(OSError, ntpath.realpath, ABSTFN, strict=True)

        os.symlink(ABSTFN + "1", ABSTFN + "2")
        os.symlink(ABSTFN + "2", ABSTFN + "1")
        self.assertRaises(OSError, ntpath.realpath, ABSTFN + "1", strict=True)
        self.assertRaises(OSError, ntpath.realpath, ABSTFN + "2", strict=True)
        self.assertRaises(OSError, ntpath.realpath, ABSTFN + "1\\x", strict=True)
        # Windows eliminates '..' components before resolving links, so the
        # following call is not expected to raise.
        self.assertPathEqual(ntpath.realpath(ABSTFN + "1\\..", strict=True),
                             ntpath.dirname(ABSTFN))
        self.assertRaises(OSError, ntpath.realpath, ABSTFN + "1\\..\\x", strict=True)
        os.symlink(ABSTFN + "x", ABSTFN + "y")
        self.assertRaises(OSError, ntpath.realpath, ABSTFN + "1\\..\\"
                                             + ntpath.basename(ABSTFN) + "y",
                                             strict=True)
        self.assertRaises(OSError, ntpath.realpath,
                          ABSTFN + "1\\..\\" + ntpath.basename(ABSTFN) + "1",
                          strict=True)

        os.symlink(ntpath.basename(ABSTFN) + "a\\b", ABSTFN + "a")
        self.assertRaises(OSError, ntpath.realpath, ABSTFN + "a", strict=True)

        os.symlink("..\\" + ntpath.basename(ntpath.dirname(ABSTFN))
                   + "\\" + ntpath.basename(ABSTFN) + "c", ABSTFN + "c")
        self.assertRaises(OSError, ntpath.realpath, ABSTFN + "c", strict=True)

        # Test using relative path as well.
        self.assertRaises(OSError, ntpath.realpath, ntpath.basename(ABSTFN),
                          strict=True)

    @os_helper.skip_unless_symlink
    @unittest.skipUnless(HAVE_GETFINALPATHNAME, 'need _getfinalpathname')
    def test_realpath_symlink_prefix(self):
        ABSTFN = ntpath.abspath(os_helper.TESTFN)
        self.addCleanup(os_helper.unlink, ABSTFN + "3")
        self.addCleanup(os_helper.unlink, "\\\\?\\" + ABSTFN + "3.")
        self.addCleanup(os_helper.unlink, ABSTFN + "3link")
        self.addCleanup(os_helper.unlink, ABSTFN + "3.link")

        with open(ABSTFN + "3", "wb") as f:
            f.write(b'0')
        os.symlink(ABSTFN + "3", ABSTFN + "3link")

        with open("\\\\?\\" + ABSTFN + "3.", "wb") as f:
            f.write(b'1')
        os.symlink("\\\\?\\" + ABSTFN + "3.", ABSTFN + "3.link")

        self.assertPathEqual(ntpath.realpath(ABSTFN + "3link"),
                             ABSTFN + "3")
        self.assertPathEqual(ntpath.realpath(ABSTFN + "3.link"),
                             "\\\\?\\" + ABSTFN + "3.")

        # Resolved paths should be usable to open target files
        with open(ntpath.realpath(ABSTFN + "3link"), "rb") as f:
            self.assertEqual(f.read(), b'0')
        with open(ntpath.realpath(ABSTFN + "3.link"), "rb") as f:
            self.assertEqual(f.read(), b'1')

        # When the prefix is included, it is not stripped
        self.assertPathEqual(ntpath.realpath("\\\\?\\" + ABSTFN + "3link"),
                             "\\\\?\\" + ABSTFN + "3")
        self.assertPathEqual(ntpath.realpath("\\\\?\\" + ABSTFN + "3.link"),
                             "\\\\?\\" + ABSTFN + "3.")

    @unittest.skipUnless(HAVE_GETFINALPATHNAME, 'need _getfinalpathname')
    def test_realpath_nul(self):
        tester("ntpath.realpath('NUL')", r'\\.\NUL')

    @unittest.skipUnless(HAVE_GETFINALPATHNAME, 'need _getfinalpathname')
    @unittest.skipUnless(HAVE_GETSHORTPATHNAME, 'need _getshortpathname')
    def test_realpath_cwd(self):
        ABSTFN = ntpath.abspath(os_helper.TESTFN)

        os_helper.unlink(ABSTFN)
        os_helper.rmtree(ABSTFN)
        os.mkdir(ABSTFN)
        self.addCleanup(os_helper.rmtree, ABSTFN)

        test_dir_long = ntpath.join(ABSTFN, "MyVeryLongDirectoryName")
        os.mkdir(test_dir_long)

        test_dir_short = _getshortpathname(test_dir_long)
        test_file_long = ntpath.join(test_dir_long, "file.txt")
        test_file_short = ntpath.join(test_dir_short, "file.txt")

        with open(test_file_long, "wb") as f:
            f.write(b"content")

        self.assertPathEqual(test_file_long, ntpath.realpath(test_file_short))

        with os_helper.change_cwd(test_dir_long):
            self.assertPathEqual(test_file_long, ntpath.realpath("file.txt"))
        with os_helper.change_cwd(test_dir_long.lower()):
            self.assertPathEqual(test_file_long, ntpath.realpath("file.txt"))
        with os_helper.change_cwd(test_dir_short):
            self.assertPathEqual(test_file_long, ntpath.realpath("file.txt"))

    def test_expandvars(self):
        with os_helper.EnvironmentVarGuard() as env:
            env.clear()
            env["foo"] = "bar"
            env["{foo"] = "baz1"
            env["{foo}"] = "baz2"
            tester('ntpath.expandvars("foo")', "foo")
            tester('ntpath.expandvars("$foo bar")', "bar bar")
            tester('ntpath.expandvars("${foo}bar")', "barbar")
            tester('ntpath.expandvars("$[foo]bar")', "$[foo]bar")
            tester('ntpath.expandvars("$bar bar")', "$bar bar")
            tester('ntpath.expandvars("$?bar")', "$?bar")
            tester('ntpath.expandvars("$foo}bar")', "bar}bar")
            tester('ntpath.expandvars("${foo")', "${foo")
            tester('ntpath.expandvars("${{foo}}")', "baz1}")
            tester('ntpath.expandvars("$foo$foo")', "barbar")
            tester('ntpath.expandvars("$bar$bar")', "$bar$bar")
            tester('ntpath.expandvars("%foo% bar")', "bar bar")
            tester('ntpath.expandvars("%foo%bar")', "barbar")
            tester('ntpath.expandvars("%foo%%foo%")', "barbar")
            tester('ntpath.expandvars("%%foo%%foo%foo%")', "%foo%foobar")
            tester('ntpath.expandvars("%?bar%")', "%?bar%")
            tester('ntpath.expandvars("%foo%%bar")', "bar%bar")
            tester('ntpath.expandvars("\'%foo%\'%bar")', "\'%foo%\'%bar")
            tester('ntpath.expandvars("bar\'%foo%")', "bar\'%foo%")

    @unittest.skipUnless(os_helper.FS_NONASCII, 'need os_helper.FS_NONASCII')
    def test_expandvars_nonascii(self):
        def check(value, expected):
            tester('ntpath.expandvars(%r)' % value, expected)
        with os_helper.EnvironmentVarGuard() as env:
            env.clear()
            nonascii = os_helper.FS_NONASCII
            env['spam'] = nonascii
            env[nonascii] = 'ham' + nonascii
            check('$spam bar', '%s bar' % nonascii)
            check('$%s bar' % nonascii, '$%s bar' % nonascii)
            check('${spam}bar', '%sbar' % nonascii)
            check('${%s}bar' % nonascii, 'ham%sbar' % nonascii)
            check('$spam}bar', '%s}bar' % nonascii)
            check('$%s}bar' % nonascii, '$%s}bar' % nonascii)
            check('%spam% bar', '%s bar' % nonascii)
            check('%{}% bar'.format(nonascii), 'ham%s bar' % nonascii)
            check('%spam%bar', '%sbar' % nonascii)
            check('%{}%bar'.format(nonascii), 'ham%sbar' % nonascii)

    def test_expanduser(self):
        tester('ntpath.expanduser("test")', 'test')

        with os_helper.EnvironmentVarGuard() as env:
            env.clear()
            tester('ntpath.expanduser("~test")', '~test')

            env['HOMEDRIVE'] = 'C:\\'
            env['HOMEPATH'] = 'Users\\eric'
            env['USERNAME'] = 'eric'
            tester('ntpath.expanduser("~test")', 'C:\\Users\\test')
            tester('ntpath.expanduser("~")', 'C:\\Users\\eric')

            del env['HOMEDRIVE']
            tester('ntpath.expanduser("~test")', 'Users\\test')
            tester('ntpath.expanduser("~")', 'Users\\eric')

            env.clear()
            env['USERPROFILE'] = 'C:\\Users\\eric'
            env['USERNAME'] = 'eric'
            tester('ntpath.expanduser("~test")', 'C:\\Users\\test')
            tester('ntpath.expanduser("~")', 'C:\\Users\\eric')
            tester('ntpath.expanduser("~test\\foo\\bar")',
                   'C:\\Users\\test\\foo\\bar')
            tester('ntpath.expanduser("~test/foo/bar")',
                   'C:\\Users\\test/foo/bar')
            tester('ntpath.expanduser("~\\foo\\bar")',
                   'C:\\Users\\eric\\foo\\bar')
            tester('ntpath.expanduser("~/foo/bar")',
                   'C:\\Users\\eric/foo/bar')

            # bpo-36264: ignore `HOME` when set on windows
            env.clear()
            env['HOME'] = 'F:\\'
            env['USERPROFILE'] = 'C:\\Users\\eric'
            env['USERNAME'] = 'eric'
            tester('ntpath.expanduser("~test")', 'C:\\Users\\test')
            tester('ntpath.expanduser("~")', 'C:\\Users\\eric')

            # bpo-39899: don't guess another user's home directory if
            # `%USERNAME% != basename(%USERPROFILE%)`
            env.clear()
            env['USERPROFILE'] = 'C:\\Users\\eric'
            env['USERNAME'] = 'idle'
            tester('ntpath.expanduser("~test")', '~test')
            tester('ntpath.expanduser("~")', 'C:\\Users\\eric')



    @unittest.skipUnless(nt, "abspath requires 'nt' module")
    def test_abspath(self):
        tester('ntpath.abspath("C:\\")', "C:\\")
        tester('ntpath.abspath("\\\\?\\C:////spam////eggs. . .")', "\\\\?\\C:\\spam\\eggs")
        tester('ntpath.abspath("\\\\.\\C:////spam////eggs. . .")', "\\\\.\\C:\\spam\\eggs")
        tester('ntpath.abspath("//spam//eggs. . .")',     "\\\\spam\\eggs")
        tester('ntpath.abspath("\\\\spam\\\\eggs. . .")', "\\\\spam\\eggs")
        tester('ntpath.abspath("C:/spam. . .")',  "C:\\spam")
        tester('ntpath.abspath("C:\\spam. . .")', "C:\\spam")
        tester('ntpath.abspath("C:/nul")',  "\\\\.\\nul")
        tester('ntpath.abspath("C:\\nul")', "\\\\.\\nul")
        tester('ntpath.abspath("//..")',           "\\\\")
        tester('ntpath.abspath("//../")',          "\\\\..\\")
        tester('ntpath.abspath("//../..")',        "\\\\..\\")
        tester('ntpath.abspath("//../../")',       "\\\\..\\..\\")
        tester('ntpath.abspath("//../../../")',    "\\\\..\\..\\")
        tester('ntpath.abspath("//../../../..")',  "\\\\..\\..\\")
        tester('ntpath.abspath("//../../../../")', "\\\\..\\..\\")
        tester('ntpath.abspath("//server")',           "\\\\server")
        tester('ntpath.abspath("//server/")',          "\\\\server\\")
        tester('ntpath.abspath("//server/..")',        "\\\\server\\")
        tester('ntpath.abspath("//server/../")',       "\\\\server\\..\\")
        tester('ntpath.abspath("//server/../..")',     "\\\\server\\..\\")
        tester('ntpath.abspath("//server/../../")',    "\\\\server\\..\\")
        tester('ntpath.abspath("//server/../../..")',  "\\\\server\\..\\")
        tester('ntpath.abspath("//server/../../../")', "\\\\server\\..\\")
        tester('ntpath.abspath("//server/share")',        "\\\\server\\share")
        tester('ntpath.abspath("//server/share/")',       "\\\\server\\share\\")
        tester('ntpath.abspath("//server/share/..")',     "\\\\server\\share\\")
        tester('ntpath.abspath("//server/share/../")',    "\\\\server\\share\\")
        tester('ntpath.abspath("//server/share/../..")',  "\\\\server\\share\\")
        tester('ntpath.abspath("//server/share/../../")', "\\\\server\\share\\")
        tester('ntpath.abspath("C:\\nul. . .")', "\\\\.\\nul")
        tester('ntpath.abspath("//... . .")',  "\\\\")
        tester('ntpath.abspath("//.. . . .")', "\\\\")
        tester('ntpath.abspath("//../... . .")',  "\\\\..\\")
        tester('ntpath.abspath("//../.. . . .")', "\\\\..\\")
        with os_helper.temp_cwd(os_helper.TESTFN) as cwd_dir: # bpo-31047
            tester('ntpath.abspath("")', cwd_dir)
            tester('ntpath.abspath(" ")', cwd_dir + "\\ ")
            tester('ntpath.abspath("?")', cwd_dir + "\\?")
            drive, _ = ntpath.splitdrive(cwd_dir)
            tester('ntpath.abspath("/abc/")', drive + "\\abc")

    def test_relpath(self):
        tester('ntpath.relpath("a")', 'a')
        tester('ntpath.relpath(ntpath.abspath("a"))', 'a')
        tester('ntpath.relpath("a/b")', 'a\\b')
        tester('ntpath.relpath("../a/b")', '..\\a\\b')
        with os_helper.temp_cwd(os_helper.TESTFN) as cwd_dir:
            currentdir = ntpath.basename(cwd_dir)
            tester('ntpath.relpath("a", "../b")', '..\\'+currentdir+'\\a')
            tester('ntpath.relpath("a/b", "../c")', '..\\'+currentdir+'\\a\\b')
        tester('ntpath.relpath("a", "b/c")', '..\\..\\a')
        tester('ntpath.relpath("c:/foo/bar/bat", "c:/x/y")', '..\\..\\foo\\bar\\bat')
        tester('ntpath.relpath("//conky/mountpoint/a", "//conky/mountpoint/b/c")', '..\\..\\a')
        tester('ntpath.relpath("a", "a")', '.')
        tester('ntpath.relpath("/foo/bar/bat", "/x/y/z")', '..\\..\\..\\foo\\bar\\bat')
        tester('ntpath.relpath("/foo/bar/bat", "/foo/bar")', 'bat')
        tester('ntpath.relpath("/foo/bar/bat", "/")', 'foo\\bar\\bat')
        tester('ntpath.relpath("/", "/foo/bar/bat")', '..\\..\\..')
        tester('ntpath.relpath("/foo/bar/bat", "/x")', '..\\foo\\bar\\bat')
        tester('ntpath.relpath("/x", "/foo/bar/bat")', '..\\..\\..\\x')
        tester('ntpath.relpath("/", "/")', '.')
        tester('ntpath.relpath("/a", "/a")', '.')
        tester('ntpath.relpath("/a/b", "/a/b")', '.')
        tester('ntpath.relpath("c:/foo", "C:/FOO")', '.')

    def test_commonpath(self):
        def check(paths, expected):
            tester(('ntpath.commonpath(%r)' % paths).replace('\\\\', '\\'),
                   expected)
        def check_error(exc, paths):
            self.assertRaises(exc, ntpath.commonpath, paths)
            self.assertRaises(exc, ntpath.commonpath,
                              [os.fsencode(p) for p in paths])

        self.assertRaises(ValueError, ntpath.commonpath, [])
        check_error(ValueError, ['C:\\Program Files', 'Program Files'])
        check_error(ValueError, ['C:\\Program Files', 'C:Program Files'])
        check_error(ValueError, ['\\Program Files', 'Program Files'])
        check_error(ValueError, ['Program Files', 'C:\\Program Files'])
        check(['C:\\Program Files'], 'C:\\Program Files')
        check(['C:\\Program Files', 'C:\\Program Files'], 'C:\\Program Files')
        check(['C:\\Program Files\\', 'C:\\Program Files'],
              'C:\\Program Files')
        check(['C:\\Program Files\\', 'C:\\Program Files\\'],
              'C:\\Program Files')
        check(['C:\\\\Program Files', 'C:\\Program Files\\\\'],
              'C:\\Program Files')
        check(['C:\\.\\Program Files', 'C:\\Program Files\\.'],
              'C:\\Program Files')
        check(['C:\\', 'C:\\bin'], 'C:\\')
        check(['C:\\Program Files', 'C:\\bin'], 'C:\\')
        check(['C:\\Program Files', 'C:\\Program Files\\Bar'],
              'C:\\Program Files')
        check(['C:\\Program Files\\Foo', 'C:\\Program Files\\Bar'],
              'C:\\Program Files')
        check(['C:\\Program Files', 'C:\\Projects'], 'C:\\')
        check(['C:\\Program Files\\', 'C:\\Projects'], 'C:\\')

        check(['C:\\Program Files\\Foo', 'C:/Program Files/Bar'],
              'C:\\Program Files')
        check(['C:\\Program Files\\Foo', 'c:/program files/bar'],
              'C:\\Program Files')
        check(['c:/program files/bar', 'C:\\Program Files\\Foo'],
              'c:\\program files')

        check_error(ValueError, ['C:\\Program Files', 'D:\\Program Files'])

        check(['spam'], 'spam')
        check(['spam', 'spam'], 'spam')
        check(['spam', 'alot'], '')
        check(['and\\jam', 'and\\spam'], 'and')
        check(['and\\\\jam', 'and\\spam\\\\'], 'and')
        check(['and\\.\\jam', '.\\and\\spam'], 'and')
        check(['and\\jam', 'and\\spam', 'alot'], '')
        check(['and\\jam', 'and\\spam', 'and'], 'and')
        check(['C:and\\jam', 'C:and\\spam'], 'C:and')

        check([''], '')
        check(['', 'spam\\alot'], '')
        check_error(ValueError, ['', '\\spam\\alot'])

        self.assertRaises(TypeError, ntpath.commonpath,
                          [b'C:\\Program Files', 'C:\\Program Files\\Foo'])
        self.assertRaises(TypeError, ntpath.commonpath,
                          [b'C:\\Program Files', 'Program Files\\Foo'])
        self.assertRaises(TypeError, ntpath.commonpath,
                          [b'Program Files', 'C:\\Program Files\\Foo'])
        self.assertRaises(TypeError, ntpath.commonpath,
                          ['C:\\Program Files', b'C:\\Program Files\\Foo'])
        self.assertRaises(TypeError, ntpath.commonpath,
                          ['C:\\Program Files', b'Program Files\\Foo'])
        self.assertRaises(TypeError, ntpath.commonpath,
                          ['Program Files', b'C:\\Program Files\\Foo'])

    @unittest.skipIf(is_emscripten, "Emscripten cannot fstat unnamed files.")
    def test_sameopenfile(self):
        with TemporaryFile() as tf1, TemporaryFile() as tf2:
            # Make sure the same file is really the same
            self.assertTrue(ntpath.sameopenfile(tf1.fileno(), tf1.fileno()))
            # Make sure different files are really different
            self.assertFalse(ntpath.sameopenfile(tf1.fileno(), tf2.fileno()))
            # Make sure invalid values don't cause issues on win32
            if sys.platform == "win32":
                with self.assertRaises(OSError):
                    # Invalid file descriptors shouldn't display assert
                    # dialogs (#4804)
                    ntpath.sameopenfile(-1, -1)

    def test_ismount(self):
        self.assertTrue(ntpath.ismount("c:\\"))
        self.assertTrue(ntpath.ismount("C:\\"))
        self.assertTrue(ntpath.ismount("c:/"))
        self.assertTrue(ntpath.ismount("C:/"))
        self.assertTrue(ntpath.ismount("\\\\.\\c:\\"))
        self.assertTrue(ntpath.ismount("\\\\.\\C:\\"))

        self.assertTrue(ntpath.ismount(b"c:\\"))
        self.assertTrue(ntpath.ismount(b"C:\\"))
        self.assertTrue(ntpath.ismount(b"c:/"))
        self.assertTrue(ntpath.ismount(b"C:/"))
        self.assertTrue(ntpath.ismount(b"\\\\.\\c:\\"))
        self.assertTrue(ntpath.ismount(b"\\\\.\\C:\\"))

        with os_helper.temp_dir() as d:
            self.assertFalse(ntpath.ismount(d))

        if sys.platform == "win32":
            #
            # Make sure the current folder isn't the root folder
            # (or any other volume root). The drive-relative
            # locations below cannot then refer to mount points
            #
            test_cwd = os.getenv("SystemRoot")
            drive, path = ntpath.splitdrive(test_cwd)
            with os_helper.change_cwd(test_cwd):
                self.assertFalse(ntpath.ismount(drive.lower()))
                self.assertFalse(ntpath.ismount(drive.upper()))

            self.assertTrue(ntpath.ismount("\\\\localhost\\c$"))
            self.assertTrue(ntpath.ismount("\\\\localhost\\c$\\"))

            self.assertTrue(ntpath.ismount(b"\\\\localhost\\c$"))
            self.assertTrue(ntpath.ismount(b"\\\\localhost\\c$\\"))

    def assertEqualCI(self, s1, s2):
        """Assert that two strings are equal ignoring case differences."""
        self.assertEqual(s1.lower(), s2.lower())

    @unittest.skipUnless(nt, "OS helpers require 'nt' module")
    def test_nt_helpers(self):
        # Trivial validation that the helpers do not break, and support both
        # unicode and bytes (UTF-8) paths

        executable = nt._getfinalpathname(sys.executable)

        for path in executable, os.fsencode(executable):
            volume_path = nt._getvolumepathname(path)
            path_drive = ntpath.splitdrive(path)[0]
            volume_path_drive = ntpath.splitdrive(volume_path)[0]
            self.assertEqualCI(path_drive, volume_path_drive)

        cap, free = nt._getdiskusage(sys.exec_prefix)
        self.assertGreater(cap, 0)
        self.assertGreater(free, 0)
        b_cap, b_free = nt._getdiskusage(sys.exec_prefix.encode())
        # Free space may change, so only test the capacity is equal
        self.assertEqual(b_cap, cap)
        self.assertGreater(b_free, 0)

        for path in [sys.prefix, sys.executable]:
            final_path = nt._getfinalpathname(path)
            self.assertIsInstance(final_path, str)
            self.assertGreater(len(final_path), 0)

            b_final_path = nt._getfinalpathname(path.encode())
            self.assertIsInstance(b_final_path, bytes)
            self.assertGreater(len(b_final_path), 0)

    @unittest.skipIf(sys.platform != 'win32', "Can only test junctions with creation on win32.")
    def test_isjunction(self):
        with os_helper.temp_dir() as d:
            with os_helper.change_cwd(d):
                os.mkdir('tmpdir')

                import _winapi
                try:
                    _winapi.CreateJunction('tmpdir', 'testjunc')
                except OSError:
                    raise unittest.SkipTest('creating the test junction failed')

                self.assertTrue(ntpath.isjunction('testjunc'))
                self.assertFalse(ntpath.isjunction('tmpdir'))
                self.assertPathEqual(ntpath.realpath('testjunc'), ntpath.realpath('tmpdir'))

    @unittest.skipIf(sys.platform != 'win32', "drive letters are a windows concept")
    def test_isfile_driveletter(self):
        drive = os.environ.get('SystemDrive')
        if drive is None or len(drive) != 2 or drive[1] != ':':
            raise unittest.SkipTest('SystemDrive is not defined or malformed')
        self.assertFalse(os.path.isfile('\\\\.\\' + drive))

    @unittest.skipIf(sys.platform != 'win32', "windows only")
    def test_con_device(self):
        self.assertFalse(os.path.isfile(r"\\.\CON"))
        self.assertFalse(os.path.isdir(r"\\.\CON"))
        self.assertFalse(os.path.islink(r"\\.\CON"))
        self.assertTrue(os.path.exists(r"\\.\CON"))

    @unittest.skipIf(sys.platform != 'win32', "Fast paths are only for win32")
    @cpython_only
    def test_fast_paths_in_use(self):
        # There are fast paths of these functions implemented in posixmodule.c.
        # Confirm that they are being used, and not the Python fallbacks in
        # genericpath.py.
        self.assertTrue(os.path.isdir is nt._path_isdir)
        self.assertFalse(inspect.isfunction(os.path.isdir))
        self.assertTrue(os.path.isfile is nt._path_isfile)
        self.assertFalse(inspect.isfunction(os.path.isfile))
        self.assertTrue(os.path.islink is nt._path_islink)
        self.assertFalse(inspect.isfunction(os.path.islink))
        self.assertTrue(os.path.exists is nt._path_exists)
        self.assertFalse(inspect.isfunction(os.path.exists))


class NtCommonTest(test_genericpath.CommonTest, unittest.TestCase):
    pathmodule = ntpath
    attributes = ['relpath']


class PathLikeTests(NtpathTestCase):

    path = ntpath

    def setUp(self):
        self.file_name = os_helper.TESTFN
        self.file_path = FakePath(os_helper.TESTFN)
        self.addCleanup(os_helper.unlink, self.file_name)
        with open(self.file_name, 'xb', 0) as file:
            file.write(b"test_ntpath.PathLikeTests")

    def _check_function(self, func):
        self.assertPathEqual(func(self.file_path), func(self.file_name))

    def test_path_normcase(self):
        self._check_function(self.path.normcase)
        if sys.platform == 'win32':
            self.assertEqual(ntpath.normcase('\u03a9\u2126'), 'ωΩ')

    def test_path_isabs(self):
        self._check_function(self.path.isabs)

    def test_path_join(self):
        self.assertEqual(self.path.join('a', FakePath('b'), 'c'),
                         self.path.join('a', 'b', 'c'))

    def test_path_split(self):
        self._check_function(self.path.split)

    def test_path_splitext(self):
        self._check_function(self.path.splitext)

    def test_path_splitdrive(self):
        self._check_function(self.path.splitdrive)

    def test_path_splitroot(self):
        self._check_function(self.path.splitroot)

    def test_path_basename(self):
        self._check_function(self.path.basename)

    def test_path_dirname(self):
        self._check_function(self.path.dirname)

    def test_path_islink(self):
        self._check_function(self.path.islink)

    def test_path_lexists(self):
        self._check_function(self.path.lexists)

    def test_path_ismount(self):
        self._check_function(self.path.ismount)

    def test_path_expanduser(self):
        self._check_function(self.path.expanduser)

    def test_path_expandvars(self):
        self._check_function(self.path.expandvars)

    def test_path_normpath(self):
        self._check_function(self.path.normpath)

    def test_path_abspath(self):
        self._check_function(self.path.abspath)

    def test_path_realpath(self):
        self._check_function(self.path.realpath)

    def test_path_relpath(self):
        self._check_function(self.path.relpath)

    def test_path_commonpath(self):
        common_path = self.path.commonpath([self.file_path, self.file_name])
        self.assertPathEqual(common_path, self.file_name)

    def test_path_isdir(self):
        self._check_function(self.path.isdir)


if __name__ == "__main__":
    unittest.main()
# test interactions between int, float, Decimal and Fraction

import unittest
import random
import math
import sys
import operator

from decimal import Decimal as D
from fractions import Fraction as F

# Constants related to the hash implementation;  hash(x) is based
# on the reduction of x modulo the prime _PyHASH_MODULUS.
_PyHASH_MODULUS = sys.hash_info.modulus
_PyHASH_INF = sys.hash_info.inf


class DummyIntegral(int):
    """Dummy Integral class to test conversion of the Rational to float."""

    def __mul__(self, other):
        return DummyIntegral(super().__mul__(other))
    __rmul__ = __mul__

    def __truediv__(self, other):
        return NotImplemented
    __rtruediv__ = __truediv__

    @property
    def numerator(self):
        return DummyIntegral(self)

    @property
    def denominator(self):
        return DummyIntegral(1)


class HashTest(unittest.TestCase):
    def check_equal_hash(self, x, y):
        # check both that x and y are equal and that their hashes are equal
        self.assertEqual(hash(x), hash(y),
                         "got different hashes for {!r} and {!r}".format(x, y))
        self.assertEqual(x, y)

    def test_bools(self):
        self.check_equal_hash(False, 0)
        self.check_equal_hash(True, 1)

    def test_integers(self):
        # check that equal values hash equal

        # exact integers
        for i in range(-1000, 1000):
            self.check_equal_hash(i, float(i))
            self.check_equal_hash(i, D(i))
            self.check_equal_hash(i, F(i))

        # the current hash is based on reduction modulo 2**n-1 for some
        # n, so pay special attention to numbers of the form 2**n and 2**n-1.
        for i in range(100):
            n = 2**i - 1
            if n == int(float(n)):
                self.check_equal_hash(n, float(n))
                self.check_equal_hash(-n, -float(n))
            self.check_equal_hash(n, D(n))
            self.check_equal_hash(n, F(n))
            self.check_equal_hash(-n, D(-n))
            self.check_equal_hash(-n, F(-n))

            n = 2**i
            self.check_equal_hash(n, float(n))
            self.check_equal_hash(-n, -float(n))
            self.check_equal_hash(n, D(n))
            self.check_equal_hash(n, F(n))
            self.check_equal_hash(-n, D(-n))
            self.check_equal_hash(-n, F(-n))

        # random values of various sizes
        for _ in range(1000):
            e = random.randrange(300)
            n = random.randrange(-10**e, 10**e)
            self.check_equal_hash(n, D(n))
            self.check_equal_hash(n, F(n))
            if n == int(float(n)):
                self.check_equal_hash(n, float(n))

    def test_binary_floats(self):
        # check that floats hash equal to corresponding Fractions and Decimals

        # floats that are distinct but numerically equal should hash the same
        self.check_equal_hash(0.0, -0.0)

        # zeros
        self.check_equal_hash(0.0, D(0))
        self.check_equal_hash(-0.0, D(0))
        self.check_equal_hash(-0.0, D('-0.0'))
        self.check_equal_hash(0.0, F(0))

        # infinities and nans
        self.check_equal_hash(float('inf'), D('inf'))
        self.check_equal_hash(float('-inf'), D('-inf'))

        for _ in range(1000):
            x = random.random() * math.exp(random.random()*200.0 - 100.0)
            self.check_equal_hash(x, D.from_float(x))
            self.check_equal_hash(x, F.from_float(x))

    def test_complex(self):
        # complex numbers with zero imaginary part should hash equal to
        # the corresponding float

        test_values = [0.0, -0.0, 1.0, -1.0, 0.40625, -5136.5,
                       float('inf'), float('-inf')]

        for zero in -0.0, 0.0:
            for value in test_values:
                self.check_equal_hash(value, complex(value, zero))

    def test_decimals(self):
        # check that Decimal instances that have different representations
        # but equal values give the same hash
        zeros = ['0', '-0', '0.0', '-0.0e10', '000e-10']
        for zero in zeros:
            self.check_equal_hash(D(zero), D(0))

        self.check_equal_hash(D('1.00'), D(1))
        self.check_equal_hash(D('1.00000'), D(1))
        self.check_equal_hash(D('-1.00'), D(-1))
        self.check_equal_hash(D('-1.00000'), D(-1))
        self.check_equal_hash(D('123e2'), D(12300))
        self.check_equal_hash(D('1230e1'), D(12300))
        self.check_equal_hash(D('12300'), D(12300))
        self.check_equal_hash(D('12300.0'), D(12300))
        self.check_equal_hash(D('12300.00'), D(12300))
        self.check_equal_hash(D('12300.000'), D(12300))

    def test_fractions(self):
        # check special case for fractions where either the numerator
        # or the denominator is a multiple of _PyHASH_MODULUS
        self.assertEqual(hash(F(1, _PyHASH_MODULUS)), _PyHASH_INF)
        self.assertEqual(hash(F(-1, 3*_PyHASH_MODULUS)), -_PyHASH_INF)
        self.assertEqual(hash(F(7*_PyHASH_MODULUS, 1)), 0)
        self.assertEqual(hash(F(-_PyHASH_MODULUS, 1)), 0)

        # The numbers ABC doesn't enforce that the "true" division
        # of integers produces a float.  This tests that the
        # Rational.__float__() method has required type conversions.
        x = F(DummyIntegral(1), DummyIntegral(2), _normalize=False)
        self.assertRaises(TypeError, lambda: x.numerator/x.denominator)
        self.assertEqual(float(x), 0.5)

    def test_hash_normalization(self):
        # Test for a bug encountered while changing long_hash.
        #
        # Given objects x and y, it should be possible for y's
        # __hash__ method to return hash(x) in order to ensure that
        # hash(x) == hash(y).  But hash(x) is not exactly equal to the
        # result of x.__hash__(): there's some internal normalization
        # to make sure that the result fits in a C long, and is not
        # equal to the invalid hash value -1.  This internal
        # normalization must therefore not change the result of
        # hash(x) for any x.

        class HalibutProxy:
            def __hash__(self):
                return hash('halibut')
            def __eq__(self, other):
                return other == 'halibut'

        x = {'halibut', HalibutProxy()}
        self.assertEqual(len(x), 1)

class ComparisonTest(unittest.TestCase):
    def test_mixed_comparisons(self):

        # ordered list of distinct test values of various types:
        # int, float, Fraction, Decimal
        test_values = [
            float('-inf'),
            D('-1e425000000'),
            -1e308,
            F(-22, 7),
            -3.14,
            -2,
            0.0,
            1e-320,
            True,
            F('1.2'),
            D('1.3'),
            float('1.4'),
            F(275807, 195025),
            D('1.414213562373095048801688724'),
            F(114243, 80782),
            F(473596569, 84615),
            7e200,
            D('infinity'),
            ]
        for i, first in enumerate(test_values):
            for second in test_values[i+1:]:
                self.assertLess(first, second)
                self.assertLessEqual(first, second)
                self.assertGreater(second, first)
                self.assertGreaterEqual(second, first)

    def test_complex(self):
        # comparisons with complex are special:  equality and inequality
        # comparisons should always succeed, but order comparisons should
        # raise TypeError.
        z = 1.0 + 0j
        w = -3.14 + 2.7j

        for v in 1, 1.0, F(1), D(1), complex(1):
            self.assertEqual(z, v)
            self.assertEqual(v, z)

        for v in 2, 2.0, F(2), D(2), complex(2):
            self.assertNotEqual(z, v)
            self.assertNotEqual(v, z)
            self.assertNotEqual(w, v)
            self.assertNotEqual(v, w)

        for v in (1, 1.0, F(1), D(1), complex(1),
                  2, 2.0, F(2), D(2), complex(2), w):
            for op in operator.le, operator.lt, operator.ge, operator.gt:
                self.assertRaises(TypeError, op, z, v)
                self.assertRaises(TypeError, op, v, z)


if __name__ == '__main__':
    unittest.main()
import unittest


class TestLoadAttrCache(unittest.TestCase):
    def test_descriptor_added_after_optimization(self):
        class Descriptor:
            pass

        class C:
            def __init__(self):
                self.x = 1
            x = Descriptor()

        def f(o):
            return o.x

        o = C()
        for i in range(1025):
            assert f(o) == 1

        Descriptor.__get__ = lambda self, instance, value: 2
        Descriptor.__set__ = lambda *args: None

        self.assertEqual(f(o), 2)

    def test_metaclass_descriptor_added_after_optimization(self):
        class Descriptor:
            pass

        class Metaclass(type):
            attribute = Descriptor()

        class Class(metaclass=Metaclass):
            attribute = True

        def __get__(self, instance, owner):
            return False

        def __set__(self, instance, value):
            return None

        def f():
            return Class.attribute

        for _ in range(1025):
            self.assertTrue(f())

        Descriptor.__get__ = __get__
        Descriptor.__set__ = __set__

        for _ in range(1025):
            self.assertFalse(f())

    def test_metaclass_descriptor_shadows_class_attribute(self):
        class Metaclass(type):
            @property
            def attribute(self):
                return True

        class Class(metaclass=Metaclass):
            attribute = False

        def f():
            return Class.attribute

        for _ in range(1025):
            self.assertTrue(f())

    def test_metaclass_set_descriptor_after_optimization(self):
        class Metaclass(type):
            pass

        class Class(metaclass=Metaclass):
            attribute = True

        @property
        def attribute(self):
            return False

        def f():
            return Class.attribute

        for _ in range(1025):
            self.assertTrue(f())

        Metaclass.attribute = attribute

        for _ in range(1025):
            self.assertFalse(f())

    def test_metaclass_del_descriptor_after_optimization(self):
        class Metaclass(type):
            @property
            def attribute(self):
                return True

        class Class(metaclass=Metaclass):
            attribute = False

        def f():
            return Class.attribute

        for _ in range(1025):
            self.assertTrue(f())

        del Metaclass.attribute

        for _ in range(1025):
            self.assertFalse(f())

    def test_type_descriptor_shadows_attribute_method(self):
        class Class:
            mro = None

        def f():
            return Class.mro

        for _ in range(1025):
            self.assertIsNone(f())

    def test_type_descriptor_shadows_attribute_member(self):
        class Class:
            __base__ = None

        def f():
            return Class.__base__

        for _ in range(1025):
            self.assertIs(f(), object)

    def test_type_descriptor_shadows_attribute_getset(self):
        class Class:
            __name__ = "Spam"

        def f():
            return Class.__name__

        for _ in range(1025):
            self.assertEqual(f(), "Class")

    def test_metaclass_getattribute(self):
        class Metaclass(type):
            def __getattribute__(self, name):
                return True

        class Class(metaclass=Metaclass):
            attribute = False

        def f():
            return Class.attribute

        for _ in range(1025):
            self.assertTrue(f())

    def test_metaclass_swap(self):
        class OldMetaclass(type):
            @property
            def attribute(self):
                return True

        class NewMetaclass(type):
            @property
            def attribute(self):
                return False

        class Class(metaclass=OldMetaclass):
            pass

        def f():
            return Class.attribute

        for _ in range(1025):
            self.assertTrue(f())

        Class.__class__ = NewMetaclass

        for _ in range(1025):
            self.assertFalse(f())

    def test_load_shadowing_slot_should_raise_type_error(self):
        class Class:
            __slots__ = ("slot",)

        class Sneaky:
            __slots__ = ("shadowed",)
            shadowing = Class.slot

        def f(o):
            o.shadowing

        o = Sneaky()
        o.shadowed = 42

        for _ in range(1025):
            with self.assertRaises(TypeError):
                f(o)

    def test_store_shadowing_slot_should_raise_type_error(self):
        class Class:
            __slots__ = ("slot",)

        class Sneaky:
            __slots__ = ("shadowed",)
            shadowing = Class.slot

        def f(o):
            o.shadowing = 42

        o = Sneaky()

        for _ in range(1025):
            with self.assertRaises(TypeError):
                f(o)

    def test_load_borrowed_slot_should_not_crash(self):
        class Class:
            __slots__ = ("slot",)

        class Sneaky:
            borrowed = Class.slot

        def f(o):
            o.borrowed

        o = Sneaky()

        for _ in range(1025):
            with self.assertRaises(TypeError):
                f(o)

    def test_store_borrowed_slot_should_not_crash(self):
        class Class:
            __slots__ = ("slot",)

        class Sneaky:
            borrowed = Class.slot

        def f(o):
            o.borrowed = 42

        o = Sneaky()

        for _ in range(1025):
            with self.assertRaises(TypeError):
                f(o)


class TestLoadMethodCache(unittest.TestCase):
    def test_descriptor_added_after_optimization(self):
        class Descriptor:
            pass

        class Class:
            attribute = Descriptor()

        def __get__(self, instance, owner):
            return lambda: False

        def __set__(self, instance, value):
            return None

        def attribute():
            return True

        instance = Class()
        instance.attribute = attribute

        def f():
            return instance.attribute()

        for _ in range(1025):
            self.assertTrue(f())

        Descriptor.__get__ = __get__
        Descriptor.__set__ = __set__

        for _ in range(1025):
            self.assertFalse(f())

    def test_metaclass_descriptor_added_after_optimization(self):
        class Descriptor:
            pass

        class Metaclass(type):
            attribute = Descriptor()

        class Class(metaclass=Metaclass):
            def attribute():
                return True

        def __get__(self, instance, owner):
            return lambda: False

        def __set__(self, instance, value):
            return None

        def f():
            return Class.attribute()

        for _ in range(1025):
            self.assertTrue(f())

        Descriptor.__get__ = __get__
        Descriptor.__set__ = __set__

        for _ in range(1025):
            self.assertFalse(f())

    def test_metaclass_descriptor_shadows_class_attribute(self):
        class Metaclass(type):
            @property
            def attribute(self):
                return lambda: True

        class Class(metaclass=Metaclass):
            def attribute():
                return False

        def f():
            return Class.attribute()

        for _ in range(1025):
            self.assertTrue(f())

    def test_metaclass_set_descriptor_after_optimization(self):
        class Metaclass(type):
            pass

        class Class(metaclass=Metaclass):
            def attribute():
                return True

        @property
        def attribute(self):
            return lambda: False

        def f():
            return Class.attribute()

        for _ in range(1025):
            self.assertTrue(f())

        Metaclass.attribute = attribute

        for _ in range(1025):
            self.assertFalse(f())

    def test_metaclass_del_descriptor_after_optimization(self):
        class Metaclass(type):
            @property
            def attribute(self):
                return lambda: True

        class Class(metaclass=Metaclass):
            def attribute():
                return False

        def f():
            return Class.attribute()

        for _ in range(1025):
            self.assertTrue(f())

        del Metaclass.attribute

        for _ in range(1025):
            self.assertFalse(f())

    def test_type_descriptor_shadows_attribute_method(self):
        class Class:
            def mro():
                return ["Spam", "eggs"]

        def f():
            return Class.mro()

        for _ in range(1025):
            self.assertEqual(f(), ["Spam", "eggs"])

    def test_type_descriptor_shadows_attribute_member(self):
        class Class:
            def __base__():
                return "Spam"

        def f():
            return Class.__base__()

        for _ in range(1025):
            self.assertNotEqual(f(), "Spam")

    def test_metaclass_getattribute(self):
        class Metaclass(type):
            def __getattribute__(self, name):
                return lambda: True

        class Class(metaclass=Metaclass):
            def attribute():
                return False

        def f():
            return Class.attribute()

        for _ in range(1025):
            self.assertTrue(f())

    def test_metaclass_swap(self):
        class OldMetaclass(type):
            @property
            def attribute(self):
                return lambda: True

        class NewMetaclass(type):
            @property
            def attribute(self):
                return lambda: False

        class Class(metaclass=OldMetaclass):
            pass

        def f():
            return Class.attribute()

        for _ in range(1025):
            self.assertTrue(f())

        Class.__class__ = NewMetaclass

        for _ in range(1025):
            self.assertFalse(f())


if __name__ == "__main__":
    import unittest
    unittest.main()
# Python test set -- part 2, opcodes

import unittest
from test import ann_module, support

class OpcodeTest(unittest.TestCase):

    def test_try_inside_for_loop(self):
        n = 0
        for i in range(10):
            n = n+i
            try: 1/0
            except NameError: pass
            except ZeroDivisionError: pass
            except TypeError: pass
            try: pass
            except: pass
            try: pass
            finally: pass
            n = n+i
        if n != 90:
            self.fail('try inside for')

    def test_setup_annotations_line(self):
        # check that SETUP_ANNOTATIONS does not create spurious line numbers
        try:
            with open(ann_module.__file__, encoding="utf-8") as f:
                txt = f.read()
            co = compile(txt, ann_module.__file__, 'exec')
            self.assertEqual(co.co_firstlineno, 1)
        except OSError:
            pass

    def test_default_annotations_exist(self):
        class C: pass
        self.assertEqual(C.__annotations__, {})

    def test_use_existing_annotations(self):
        ns = {'__annotations__': {1: 2}}
        exec('x: int', ns)
        self.assertEqual(ns['__annotations__'], {'x': int, 1: 2})

    def test_do_not_recreate_annotations(self):
        # Don't rely on the existence of the '__annotations__' global.
        with support.swap_item(globals(), '__annotations__', {}):
            del globals()['__annotations__']
            class C:
                del __annotations__
                with self.assertRaises(NameError):
                    x: int

    def test_raise_class_exceptions(self):

        class AClass(Exception): pass
        class BClass(AClass): pass
        class CClass(Exception): pass
        class DClass(AClass):
            def __init__(self, ignore):
                pass

        try: raise AClass()
        except: pass

        try: raise AClass()
        except AClass: pass

        try: raise BClass()
        except AClass: pass

        try: raise BClass()
        except CClass: self.fail()
        except: pass

        a = AClass()
        b = BClass()

        try:
            raise b
        except AClass as v:
            self.assertEqual(v, b)
        else:
            self.fail("no exception")

        # not enough arguments
        ##try:  raise BClass, a
        ##except TypeError: pass
        ##else: self.fail("no exception")

        try:  raise DClass(a)
        except DClass as v:
            self.assertIsInstance(v, DClass)
        else:
            self.fail("no exception")

    def test_compare_function_objects(self):

        f = eval('lambda: None')
        g = eval('lambda: None')
        self.assertNotEqual(f, g)

        f = eval('lambda a: a')
        g = eval('lambda a: a')
        self.assertNotEqual(f, g)

        f = eval('lambda a=1: a')
        g = eval('lambda a=1: a')
        self.assertNotEqual(f, g)

        f = eval('lambda: 0')
        g = eval('lambda: 1')
        self.assertNotEqual(f, g)

        f = eval('lambda: None')
        g = eval('lambda a: None')
        self.assertNotEqual(f, g)

        f = eval('lambda a: None')
        g = eval('lambda b: None')
        self.assertNotEqual(f, g)

        f = eval('lambda a: None')
        g = eval('lambda a=None: None')
        self.assertNotEqual(f, g)

        f = eval('lambda a=0: None')
        g = eval('lambda a=1: None')
        self.assertNotEqual(f, g)

    def test_modulo_of_string_subclasses(self):
        class MyString(str):
            def __mod__(self, value):
                return 42
        self.assertEqual(MyString() % 3, 42)


if __name__ == '__main__':
    unittest.main()
# Test to see if openpty works. (But don't worry if it isn't available.)

import os, unittest

if not hasattr(os, "openpty"):
    raise unittest.SkipTest("os.openpty() not available.")


class OpenptyTest(unittest.TestCase):
    def test(self):
        master, slave = os.openpty()
        self.addCleanup(os.close, master)
        self.addCleanup(os.close, slave)
        if not os.isatty(slave):
            self.fail("Slave-end of pty is not a terminal.")

        os.write(slave, b'Ping!')
        self.assertEqual(os.read(master, 1024), b'Ping!')

if __name__ == '__main__':
    unittest.main()
import unittest
import pickle
import sys

from test import support
from test.support import import_helper


py_operator = import_helper.import_fresh_module('operator',
                                                blocked=['_operator'])
c_operator = import_helper.import_fresh_module('operator',
                                               fresh=['_operator'])

class Seq1:
    def __init__(self, lst):
        self.lst = lst
    def __len__(self):
        return len(self.lst)
    def __getitem__(self, i):
        return self.lst[i]
    def __add__(self, other):
        return self.lst + other.lst
    def __mul__(self, other):
        return self.lst * other
    def __rmul__(self, other):
        return other * self.lst

class Seq2(object):
    def __init__(self, lst):
        self.lst = lst
    def __len__(self):
        return len(self.lst)
    def __getitem__(self, i):
        return self.lst[i]
    def __add__(self, other):
        return self.lst + other.lst
    def __mul__(self, other):
        return self.lst * other
    def __rmul__(self, other):
        return other * self.lst

class BadIterable:
    def __iter__(self):
        raise ZeroDivisionError


class OperatorTestCase:
    def test___all__(self):
        operator = self.module
        actual_all = set(operator.__all__)
        computed_all = set()
        for name in vars(operator):
            if name.startswith('__'):
                continue
            value = getattr(operator, name)
            if value.__module__ in ('operator', '_operator'):
                computed_all.add(name)
        self.assertSetEqual(computed_all, actual_all)

    def test_lt(self):
        operator = self.module
        self.assertRaises(TypeError, operator.lt)
        self.assertRaises(TypeError, operator.lt, 1j, 2j)
        self.assertFalse(operator.lt(1, 0))
        self.assertFalse(operator.lt(1, 0.0))
        self.assertFalse(operator.lt(1, 1))
        self.assertFalse(operator.lt(1, 1.0))
        self.assertTrue(operator.lt(1, 2))
        self.assertTrue(operator.lt(1, 2.0))

    def test_le(self):
        operator = self.module
        self.assertRaises(TypeError, operator.le)
        self.assertRaises(TypeError, operator.le, 1j, 2j)
        self.assertFalse(operator.le(1, 0))
        self.assertFalse(operator.le(1, 0.0))
        self.assertTrue(operator.le(1, 1))
        self.assertTrue(operator.le(1, 1.0))
        self.assertTrue(operator.le(1, 2))
        self.assertTrue(operator.le(1, 2.0))

    def test_eq(self):
        operator = self.module
        class C(object):
            def __eq__(self, other):
                raise SyntaxError
        self.assertRaises(TypeError, operator.eq)
        self.assertRaises(SyntaxError, operator.eq, C(), C())
        self.assertFalse(operator.eq(1, 0))
        self.assertFalse(operator.eq(1, 0.0))
        self.assertTrue(operator.eq(1, 1))
        self.assertTrue(operator.eq(1, 1.0))
        self.assertFalse(operator.eq(1, 2))
        self.assertFalse(operator.eq(1, 2.0))

    def test_ne(self):
        operator = self.module
        class C(object):
            def __ne__(self, other):
                raise SyntaxError
        self.assertRaises(TypeError, operator.ne)
        self.assertRaises(SyntaxError, operator.ne, C(), C())
        self.assertTrue(operator.ne(1, 0))
        self.assertTrue(operator.ne(1, 0.0))
        self.assertFalse(operator.ne(1, 1))
        self.assertFalse(operator.ne(1, 1.0))
        self.assertTrue(operator.ne(1, 2))
        self.assertTrue(operator.ne(1, 2.0))

    def test_ge(self):
        operator = self.module
        self.assertRaises(TypeError, operator.ge)
        self.assertRaises(TypeError, operator.ge, 1j, 2j)
        self.assertTrue(operator.ge(1, 0))
        self.assertTrue(operator.ge(1, 0.0))
        self.assertTrue(operator.ge(1, 1))
        self.assertTrue(operator.ge(1, 1.0))
        self.assertFalse(operator.ge(1, 2))
        self.assertFalse(operator.ge(1, 2.0))

    def test_gt(self):
        operator = self.module
        self.assertRaises(TypeError, operator.gt)
        self.assertRaises(TypeError, operator.gt, 1j, 2j)
        self.assertTrue(operator.gt(1, 0))
        self.assertTrue(operator.gt(1, 0.0))
        self.assertFalse(operator.gt(1, 1))
        self.assertFalse(operator.gt(1, 1.0))
        self.assertFalse(operator.gt(1, 2))
        self.assertFalse(operator.gt(1, 2.0))

    def test_abs(self):
        operator = self.module
        self.assertRaises(TypeError, operator.abs)
        self.assertRaises(TypeError, operator.abs, None)
        self.assertEqual(operator.abs(-1), 1)
        self.assertEqual(operator.abs(1), 1)

    def test_add(self):
        operator = self.module
        self.assertRaises(TypeError, operator.add)
        self.assertRaises(TypeError, operator.add, None, None)
        self.assertEqual(operator.add(3, 4), 7)

    def test_bitwise_and(self):
        operator = self.module
        self.assertRaises(TypeError, operator.and_)
        self.assertRaises(TypeError, operator.and_, None, None)
        self.assertEqual(operator.and_(0xf, 0xa), 0xa)

    def test_concat(self):
        operator = self.module
        self.assertRaises(TypeError, operator.concat)
        self.assertRaises(TypeError, operator.concat, None, None)
        self.assertEqual(operator.concat('py', 'thon'), 'python')
        self.assertEqual(operator.concat([1, 2], [3, 4]), [1, 2, 3, 4])
        self.assertEqual(operator.concat(Seq1([5, 6]), Seq1([7])), [5, 6, 7])
        self.assertEqual(operator.concat(Seq2([5, 6]), Seq2([7])), [5, 6, 7])
        self.assertRaises(TypeError, operator.concat, 13, 29)

    def test_countOf(self):
        operator = self.module
        self.assertRaises(TypeError, operator.countOf)
        self.assertRaises(TypeError, operator.countOf, None, None)
        self.assertRaises(ZeroDivisionError, operator.countOf, BadIterable(), 1)
        self.assertEqual(operator.countOf([1, 2, 1, 3, 1, 4], 3), 1)
        self.assertEqual(operator.countOf([1, 2, 1, 3, 1, 4], 5), 0)
        # is but not ==
        nan = float("nan")
        self.assertEqual(operator.countOf([nan, nan, 21], nan), 2)
        # == but not is
        self.assertEqual(operator.countOf([{}, 1, {}, 2], {}), 2)

    def test_delitem(self):
        operator = self.module
        a = [4, 3, 2, 1]
        self.assertRaises(TypeError, operator.delitem, a)
        self.assertRaises(TypeError, operator.delitem, a, None)
        self.assertIsNone(operator.delitem(a, 1))
        self.assertEqual(a, [4, 2, 1])

    def test_floordiv(self):
        operator = self.module
        self.assertRaises(TypeError, operator.floordiv, 5)
        self.assertRaises(TypeError, operator.floordiv, None, None)
        self.assertEqual(operator.floordiv(5, 2), 2)

    def test_truediv(self):
        operator = self.module
        self.assertRaises(TypeError, operator.truediv, 5)
        self.assertRaises(TypeError, operator.truediv, None, None)
        self.assertEqual(operator.truediv(5, 2), 2.5)

    def test_getitem(self):
        operator = self.module
        a = range(10)
        self.assertRaises(TypeError, operator.getitem)
        self.assertRaises(TypeError, operator.getitem, a, None)
        self.assertEqual(operator.getitem(a, 2), 2)

    def test_indexOf(self):
        operator = self.module
        self.assertRaises(TypeError, operator.indexOf)
        self.assertRaises(TypeError, operator.indexOf, None, None)
        self.assertRaises(ZeroDivisionError, operator.indexOf, BadIterable(), 1)
        self.assertEqual(operator.indexOf([4, 3, 2, 1], 3), 1)
        self.assertRaises(ValueError, operator.indexOf, [4, 3, 2, 1], 0)
        nan = float("nan")
        self.assertEqual(operator.indexOf([nan, nan, 21], nan), 0)
        self.assertEqual(operator.indexOf([{}, 1, {}, 2], {}), 0)

    def test_invert(self):
        operator = self.module
        self.assertRaises(TypeError, operator.invert)
        self.assertRaises(TypeError, operator.invert, None)
        self.assertEqual(operator.inv(4), -5)

    def test_lshift(self):
        operator = self.module
        self.assertRaises(TypeError, operator.lshift)
        self.assertRaises(TypeError, operator.lshift, None, 42)
        self.assertEqual(operator.lshift(5, 1), 10)
        self.assertEqual(operator.lshift(5, 0), 5)
        self.assertRaises(ValueError, operator.lshift, 2, -1)

    def test_mod(self):
        operator = self.module
        self.assertRaises(TypeError, operator.mod)
        self.assertRaises(TypeError, operator.mod, None, 42)
        self.assertEqual(operator.mod(5, 2), 1)

    def test_mul(self):
        operator = self.module
        self.assertRaises(TypeError, operator.mul)
        self.assertRaises(TypeError, operator.mul, None, None)
        self.assertEqual(operator.mul(5, 2), 10)

    def test_matmul(self):
        operator = self.module
        self.assertRaises(TypeError, operator.matmul)
        self.assertRaises(TypeError, operator.matmul, 42, 42)
        class M:
            def __matmul__(self, other):
                return other - 1
        self.assertEqual(M() @ 42, 41)

    def test_neg(self):
        operator = self.module
        self.assertRaises(TypeError, operator.neg)
        self.assertRaises(TypeError, operator.neg, None)
        self.assertEqual(operator.neg(5), -5)
        self.assertEqual(operator.neg(-5), 5)
        self.assertEqual(operator.neg(0), 0)
        self.assertEqual(operator.neg(-0), 0)

    def test_bitwise_or(self):
        operator = self.module
        self.assertRaises(TypeError, operator.or_)
        self.assertRaises(TypeError, operator.or_, None, None)
        self.assertEqual(operator.or_(0xa, 0x5), 0xf)

    def test_pos(self):
        operator = self.module
        self.assertRaises(TypeError, operator.pos)
        self.assertRaises(TypeError, operator.pos, None)
        self.assertEqual(operator.pos(5), 5)
        self.assertEqual(operator.pos(-5), -5)
        self.assertEqual(operator.pos(0), 0)
        self.assertEqual(operator.pos(-0), 0)

    def test_pow(self):
        operator = self.module
        self.assertRaises(TypeError, operator.pow)
        self.assertRaises(TypeError, operator.pow, None, None)
        self.assertEqual(operator.pow(3,5), 3**5)
        self.assertRaises(TypeError, operator.pow, 1)
        self.assertRaises(TypeError, operator.pow, 1, 2, 3)

    def test_rshift(self):
        operator = self.module
        self.assertRaises(TypeError, operator.rshift)
        self.assertRaises(TypeError, operator.rshift, None, 42)
        self.assertEqual(operator.rshift(5, 1), 2)
        self.assertEqual(operator.rshift(5, 0), 5)
        self.assertRaises(ValueError, operator.rshift, 2, -1)

    def test_contains(self):
        operator = self.module
        self.assertRaises(TypeError, operator.contains)
        self.assertRaises(TypeError, operator.contains, None, None)
        self.assertRaises(ZeroDivisionError, operator.contains, BadIterable(), 1)
        self.assertTrue(operator.contains(range(4), 2))
        self.assertFalse(operator.contains(range(4), 5))

    def test_setitem(self):
        operator = self.module
        a = list(range(3))
        self.assertRaises(TypeError, operator.setitem, a)
        self.assertRaises(TypeError, operator.setitem, a, None, None)
        self.assertIsNone(operator.setitem(a, 0, 2))
        self.assertEqual(a, [2, 1, 2])
        self.assertRaises(IndexError, operator.setitem, a, 4, 2)

    def test_sub(self):
        operator = self.module
        self.assertRaises(TypeError, operator.sub)
        self.assertRaises(TypeError, operator.sub, None, None)
        self.assertEqual(operator.sub(5, 2), 3)

    def test_truth(self):
        operator = self.module
        class C(object):
            def __bool__(self):
                raise SyntaxError
        self.assertRaises(TypeError, operator.truth)
        self.assertRaises(SyntaxError, operator.truth, C())
        self.assertTrue(operator.truth(5))
        self.assertTrue(operator.truth([0]))
        self.assertFalse(operator.truth(0))
        self.assertFalse(operator.truth([]))

    def test_bitwise_xor(self):
        operator = self.module
        self.assertRaises(TypeError, operator.xor)
        self.assertRaises(TypeError, operator.xor, None, None)
        self.assertEqual(operator.xor(0xb, 0xc), 0x7)

    def test_is(self):
        operator = self.module
        a = b = 'xyzpdq'
        c = a[:3] + b[3:]
        self.assertRaises(TypeError, operator.is_)
        self.assertTrue(operator.is_(a, b))
        self.assertFalse(operator.is_(a,c))

    def test_is_not(self):
        operator = self.module
        a = b = 'xyzpdq'
        c = a[:3] + b[3:]
        self.assertRaises(TypeError, operator.is_not)
        self.assertFalse(operator.is_not(a, b))
        self.assertTrue(operator.is_not(a,c))

    def test_attrgetter(self):
        operator = self.module
        class A:
            pass
        a = A()
        a.name = 'arthur'
        f = operator.attrgetter('name')
        self.assertEqual(f(a), 'arthur')
        self.assertRaises(TypeError, f)
        self.assertRaises(TypeError, f, a, 'dent')
        self.assertRaises(TypeError, f, a, surname='dent')
        f = operator.attrgetter('rank')
        self.assertRaises(AttributeError, f, a)
        self.assertRaises(TypeError, operator.attrgetter, 2)
        self.assertRaises(TypeError, operator.attrgetter)

        # multiple gets
        record = A()
        record.x = 'X'
        record.y = 'Y'
        record.z = 'Z'
        self.assertEqual(operator.attrgetter('x','z','y')(record), ('X', 'Z', 'Y'))
        self.assertRaises(TypeError, operator.attrgetter, ('x', (), 'y'))

        class C(object):
            def __getattr__(self, name):
                raise SyntaxError
        self.assertRaises(SyntaxError, operator.attrgetter('foo'), C())

        # recursive gets
        a = A()
        a.name = 'arthur'
        a.child = A()
        a.child.name = 'thomas'
        f = operator.attrgetter('child.name')
        self.assertEqual(f(a), 'thomas')
        self.assertRaises(AttributeError, f, a.child)
        f = operator.attrgetter('name', 'child.name')
        self.assertEqual(f(a), ('arthur', 'thomas'))
        f = operator.attrgetter('name', 'child.name', 'child.child.name')
        self.assertRaises(AttributeError, f, a)
        f = operator.attrgetter('child.')
        self.assertRaises(AttributeError, f, a)
        f = operator.attrgetter('.child')
        self.assertRaises(AttributeError, f, a)

        a.child.child = A()
        a.child.child.name = 'johnson'
        f = operator.attrgetter('child.child.name')
        self.assertEqual(f(a), 'johnson')
        f = operator.attrgetter('name', 'child.name', 'child.child.name')
        self.assertEqual(f(a), ('arthur', 'thomas', 'johnson'))

    def test_itemgetter(self):
        operator = self.module
        a = 'ABCDE'
        f = operator.itemgetter(2)
        self.assertEqual(f(a), 'C')
        self.assertRaises(TypeError, f)
        self.assertRaises(TypeError, f, a, 3)
        self.assertRaises(TypeError, f, a, size=3)
        f = operator.itemgetter(10)
        self.assertRaises(IndexError, f, a)

        class C(object):
            def __getitem__(self, name):
                raise SyntaxError
        self.assertRaises(SyntaxError, operator.itemgetter(42), C())

        f = operator.itemgetter('name')
        self.assertRaises(TypeError, f, a)
        self.assertRaises(TypeError, operator.itemgetter)

        d = dict(key='val')
        f = operator.itemgetter('key')
        self.assertEqual(f(d), 'val')
        f = operator.itemgetter('nonkey')
        self.assertRaises(KeyError, f, d)

        # example used in the docs
        inventory = [('apple', 3), ('banana', 2), ('pear', 5), ('orange', 1)]
        getcount = operator.itemgetter(1)
        self.assertEqual(list(map(getcount, inventory)), [3, 2, 5, 1])
        self.assertEqual(sorted(inventory, key=getcount),
            [('orange', 1), ('banana', 2), ('apple', 3), ('pear', 5)])

        # multiple gets
        data = list(map(str, range(20)))
        self.assertEqual(operator.itemgetter(2,10,5)(data), ('2', '10', '5'))
        self.assertRaises(TypeError, operator.itemgetter(2, 'x', 5), data)

        # interesting indices
        t = tuple('abcde')
        self.assertEqual(operator.itemgetter(-1)(t), 'e')
        self.assertEqual(operator.itemgetter(slice(2, 4))(t), ('c', 'd'))

        # interesting sequences
        class T(tuple):
            'Tuple subclass'
            pass
        self.assertEqual(operator.itemgetter(0)(T('abc')), 'a')
        self.assertEqual(operator.itemgetter(0)(['a', 'b', 'c']), 'a')
        self.assertEqual(operator.itemgetter(0)(range(100, 200)), 100)

    def test_methodcaller(self):
        operator = self.module
        self.assertRaises(TypeError, operator.methodcaller)
        self.assertRaises(TypeError, operator.methodcaller, 12)
        class A:
            def foo(self, *args, **kwds):
                return args[0] + args[1]
            def bar(self, f=42):
                return f
            def baz(*args, **kwds):
                return kwds['name'], kwds['self']
        a = A()
        f = operator.methodcaller('foo')
        self.assertRaises(IndexError, f, a)
        f = operator.methodcaller('foo', 1, 2)
        self.assertEqual(f(a), 3)
        self.assertRaises(TypeError, f)
        self.assertRaises(TypeError, f, a, 3)
        self.assertRaises(TypeError, f, a, spam=3)
        f = operator.methodcaller('bar')
        self.assertEqual(f(a), 42)
        self.assertRaises(TypeError, f, a, a)
        f = operator.methodcaller('bar', f=5)
        self.assertEqual(f(a), 5)
        f = operator.methodcaller('baz', name='spam', self='eggs')
        self.assertEqual(f(a), ('spam', 'eggs'))

    def test_inplace(self):
        operator = self.module
        class C(object):
            def __iadd__     (self, other): return "iadd"
            def __iand__     (self, other): return "iand"
            def __ifloordiv__(self, other): return "ifloordiv"
            def __ilshift__  (self, other): return "ilshift"
            def __imod__     (self, other): return "imod"
            def __imul__     (self, other): return "imul"
            def __imatmul__  (self, other): return "imatmul"
            def __ior__      (self, other): return "ior"
            def __ipow__     (self, other): return "ipow"
            def __irshift__  (self, other): return "irshift"
            def __isub__     (self, other): return "isub"
            def __itruediv__ (self, other): return "itruediv"
            def __ixor__     (self, other): return "ixor"
            def __getitem__(self, other): return 5  # so that C is a sequence
        c = C()
        self.assertEqual(operator.iadd     (c, 5), "iadd")
        self.assertEqual(operator.iand     (c, 5), "iand")
        self.assertEqual(operator.ifloordiv(c, 5), "ifloordiv")
        self.assertEqual(operator.ilshift  (c, 5), "ilshift")
        self.assertEqual(operator.imod     (c, 5), "imod")
        self.assertEqual(operator.imul     (c, 5), "imul")
        self.assertEqual(operator.imatmul  (c, 5), "imatmul")
        self.assertEqual(operator.ior      (c, 5), "ior")
        self.assertEqual(operator.ipow     (c, 5), "ipow")
        self.assertEqual(operator.irshift  (c, 5), "irshift")
        self.assertEqual(operator.isub     (c, 5), "isub")
        self.assertEqual(operator.itruediv (c, 5), "itruediv")
        self.assertEqual(operator.ixor     (c, 5), "ixor")
        self.assertEqual(operator.iconcat  (c, c), "iadd")

    def test_length_hint(self):
        operator = self.module
        class X(object):
            def __init__(self, value):
                self.value = value

            def __length_hint__(self):
                if type(self.value) is type:
                    raise self.value
                else:
                    return self.value

        self.assertEqual(operator.length_hint([], 2), 0)
        self.assertEqual(operator.length_hint(iter([1, 2, 3])), 3)

        self.assertEqual(operator.length_hint(X(2)), 2)
        self.assertEqual(operator.length_hint(X(NotImplemented), 4), 4)
        self.assertEqual(operator.length_hint(X(TypeError), 12), 12)
        with self.assertRaises(TypeError):
            operator.length_hint(X("abc"))
        with self.assertRaises(ValueError):
            operator.length_hint(X(-2))
        with self.assertRaises(LookupError):
            operator.length_hint(X(LookupError))

    def test_call(self):
        operator = self.module

        def func(*args, **kwargs): return args, kwargs

        self.assertEqual(operator.call(func), ((), {}))
        self.assertEqual(operator.call(func, 0, 1), ((0, 1), {}))
        self.assertEqual(operator.call(func, a=2, obj=3),
                         ((), {"a": 2, "obj": 3}))
        self.assertEqual(operator.call(func, 0, 1, a=2, obj=3),
                         ((0, 1), {"a": 2, "obj": 3}))

    def test_dunder_is_original(self):
        operator = self.module

        names = [name for name in dir(operator) if not name.startswith('_')]
        for name in names:
            orig = getattr(operator, name)
            dunder = getattr(operator, '__' + name.strip('_') + '__', None)
            if dunder:
                self.assertIs(dunder, orig)

class PyOperatorTestCase(OperatorTestCase, unittest.TestCase):
    module = py_operator

@unittest.skipUnless(c_operator, 'requires _operator')
class COperatorTestCase(OperatorTestCase, unittest.TestCase):
    module = c_operator


class OperatorPickleTestCase:
    def copy(self, obj, proto):
        with support.swap_item(sys.modules, 'operator', self.module):
            pickled = pickle.dumps(obj, proto)
        with support.swap_item(sys.modules, 'operator', self.module2):
            return pickle.loads(pickled)

    def test_attrgetter(self):
        attrgetter = self.module.attrgetter
        class A:
            pass
        a = A()
        a.x = 'X'
        a.y = 'Y'
        a.z = 'Z'
        a.t = A()
        a.t.u = A()
        a.t.u.v = 'V'
        for proto in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(proto=proto):
                f = attrgetter('x')
                f2 = self.copy(f, proto)
                self.assertEqual(repr(f2), repr(f))
                self.assertEqual(f2(a), f(a))
                # multiple gets
                f = attrgetter('x', 'y', 'z')
                f2 = self.copy(f, proto)
                self.assertEqual(repr(f2), repr(f))
                self.assertEqual(f2(a), f(a))
                # recursive gets
                f = attrgetter('t.u.v')
                f2 = self.copy(f, proto)
                self.assertEqual(repr(f2), repr(f))
                self.assertEqual(f2(a), f(a))

    def test_itemgetter(self):
        itemgetter = self.module.itemgetter
        a = 'ABCDE'
        for proto in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(proto=proto):
                f = itemgetter(2)
                f2 = self.copy(f, proto)
                self.assertEqual(repr(f2), repr(f))
                self.assertEqual(f2(a), f(a))
                # multiple gets
                f = itemgetter(2, 0, 4)
                f2 = self.copy(f, proto)
                self.assertEqual(repr(f2), repr(f))
                self.assertEqual(f2(a), f(a))

    def test_methodcaller(self):
        methodcaller = self.module.methodcaller
        class A:
            def foo(self, *args, **kwds):
                return args[0] + args[1]
            def bar(self, f=42):
                return f
            def baz(*args, **kwds):
                return kwds['name'], kwds['self']
        a = A()
        for proto in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(proto=proto):
                f = methodcaller('bar')
                f2 = self.copy(f, proto)
                self.assertEqual(repr(f2), repr(f))
                self.assertEqual(f2(a), f(a))
                # positional args
                f = methodcaller('foo', 1, 2)
                f2 = self.copy(f, proto)
                self.assertEqual(repr(f2), repr(f))
                self.assertEqual(f2(a), f(a))
                # keyword args
                f = methodcaller('bar', f=5)
                f2 = self.copy(f, proto)
                self.assertEqual(repr(f2), repr(f))
                self.assertEqual(f2(a), f(a))
                f = methodcaller('baz', self='eggs', name='spam')
                f2 = self.copy(f, proto)
                # Can't test repr consistently with multiple keyword args
                self.assertEqual(f2(a), f(a))

class PyPyOperatorPickleTestCase(OperatorPickleTestCase, unittest.TestCase):
    module = py_operator
    module2 = py_operator

@unittest.skipUnless(c_operator, 'requires _operator')
class PyCOperatorPickleTestCase(OperatorPickleTestCase, unittest.TestCase):
    module = py_operator
    module2 = c_operator

@unittest.skipUnless(c_operator, 'requires _operator')
class CPyOperatorPickleTestCase(OperatorPickleTestCase, unittest.TestCase):
    module = c_operator
    module2 = py_operator

@unittest.skipUnless(c_operator, 'requires _operator')
class CCOperatorPickleTestCase(OperatorPickleTestCase, unittest.TestCase):
    module = c_operator
    module2 = c_operator


if __name__ == "__main__":
    unittest.main()
#
# Test suite for Optik.  Supplied by Johannes Gijsbers
# (taradino@softhome.net) -- translated from the original Optik
# test suite to this PyUnit-based version.
#
# $Id$
#

import sys
import os
import re
import copy
import unittest

from io import StringIO
from test import support
from test.support import os_helper


import optparse
from optparse import make_option, Option, \
     TitledHelpFormatter, OptionParser, OptionGroup, \
     SUPPRESS_USAGE, OptionError, OptionConflictError, \
     BadOptionError, OptionValueError, Values
from optparse import _match_abbrev
from optparse import _parse_num

class InterceptedError(Exception):
    def __init__(self,
                 error_message=None,
                 exit_status=None,
                 exit_message=None):
        self.error_message = error_message
        self.exit_status = exit_status
        self.exit_message = exit_message

    def __str__(self):
        return self.error_message or self.exit_message or "intercepted error"

class InterceptingOptionParser(OptionParser):
    def exit(self, status=0, msg=None):
        raise InterceptedError(exit_status=status, exit_message=msg)

    def error(self, msg):
        raise InterceptedError(error_message=msg)


class BaseTest(unittest.TestCase):
    def assertParseOK(self, args, expected_opts, expected_positional_args):
        """Assert the options are what we expected when parsing arguments.

        Otherwise, fail with a nicely formatted message.

        Keyword arguments:
        args -- A list of arguments to parse with OptionParser.
        expected_opts -- The options expected.
        expected_positional_args -- The positional arguments expected.

        Returns the options and positional args for further testing.
        """

        (options, positional_args) = self.parser.parse_args(args)
        optdict = vars(options)

        self.assertEqual(optdict, expected_opts,
                         """
Options are %(optdict)s.
Should be %(expected_opts)s.
Args were %(args)s.""" % locals())

        self.assertEqual(positional_args, expected_positional_args,
                         """
Positional arguments are %(positional_args)s.
Should be %(expected_positional_args)s.
Args were %(args)s.""" % locals ())

        return (options, positional_args)

    def assertRaises(self,
                     func,
                     args,
                     kwargs,
                     expected_exception,
                     expected_message):
        """
        Assert that the expected exception is raised when calling a
        function, and that the right error message is included with
        that exception.

        Arguments:
          func -- the function to call
          args -- positional arguments to `func`
          kwargs -- keyword arguments to `func`
          expected_exception -- exception that should be raised
          expected_message -- expected exception message (or pattern
            if a compiled regex object)

        Returns the exception raised for further testing.
        """
        if args is None:
            args = ()
        if kwargs is None:
            kwargs = {}

        try:
            func(*args, **kwargs)
        except expected_exception as err:
            actual_message = str(err)
            if isinstance(expected_message, re.Pattern):
                self.assertTrue(expected_message.search(actual_message),
                             """\
expected exception message pattern:
/%s/
actual exception message:
'''%s'''
""" % (expected_message.pattern, actual_message))
            else:
                self.assertEqual(actual_message,
                                 expected_message,
                                 """\
expected exception message:
'''%s'''
actual exception message:
'''%s'''
""" % (expected_message, actual_message))

            return err
        else:
            self.fail("""expected exception %(expected_exception)s not raised
called %(func)r
with args %(args)r
and kwargs %(kwargs)r
""" % locals ())


    # -- Assertions used in more than one class --------------------

    def assertParseFail(self, cmdline_args, expected_output):
        """
        Assert the parser fails with the expected message.  Caller
        must ensure that self.parser is an InterceptingOptionParser.
        """
        try:
            self.parser.parse_args(cmdline_args)
        except InterceptedError as err:
            self.assertEqual(err.error_message, expected_output)
        else:
            self.assertFalse("expected parse failure")

    def assertOutput(self,
                     cmdline_args,
                     expected_output,
                     expected_status=0,
                     expected_error=None):
        """Assert the parser prints the expected output on stdout."""
        save_stdout = sys.stdout
        try:
            try:
                sys.stdout = StringIO()
                self.parser.parse_args(cmdline_args)
            finally:
                output = sys.stdout.getvalue()
                sys.stdout = save_stdout

        except InterceptedError as err:
            self.assertTrue(
                isinstance(output, str),
                "expected output to be an ordinary string, not %r"
                % type(output))

            if output != expected_output:
                self.fail("expected: \n'''\n" + expected_output +
                          "'''\nbut got \n'''\n" + output + "'''")
            self.assertEqual(err.exit_status, expected_status)
            self.assertEqual(err.exit_message, expected_error)
        else:
            self.assertFalse("expected parser.exit()")

    def assertTypeError(self, func, expected_message, *args):
        """Assert that TypeError is raised when executing func."""
        self.assertRaises(func, args, None, TypeError, expected_message)

    def assertHelp(self, parser, expected_help):
        actual_help = parser.format_help()
        if actual_help != expected_help:
            raise self.failureException(
                'help text failure; expected:\n"' +
                expected_help + '"; got:\n"' +
                actual_help + '"\n')

# -- Test make_option() aka Option -------------------------------------

# It's not necessary to test correct options here.  All the tests in the
# parser.parse_args() section deal with those, because they're needed
# there.

class TestOptionChecks(BaseTest):
    def setUp(self):
        self.parser = OptionParser(usage=SUPPRESS_USAGE)

    def assertOptionError(self, expected_message, args=[], kwargs={}):
        self.assertRaises(make_option, args, kwargs,
                          OptionError, expected_message)

    def test_opt_string_empty(self):
        self.assertTypeError(make_option,
                             "at least one option string must be supplied")

    def test_opt_string_too_short(self):
        self.assertOptionError(
            "invalid option string 'b': must be at least two characters long",
            ["b"])

    def test_opt_string_short_invalid(self):
        self.assertOptionError(
            "invalid short option string '--': must be "
            "of the form -x, (x any non-dash char)",
            ["--"])

    def test_opt_string_long_invalid(self):
        self.assertOptionError(
            "invalid long option string '---': "
            "must start with --, followed by non-dash",
            ["---"])

    def test_attr_invalid(self):
        self.assertOptionError(
            "option -b: invalid keyword arguments: bar, foo",
            ["-b"], {'foo': None, 'bar': None})

    def test_action_invalid(self):
        self.assertOptionError(
            "option -b: invalid action: 'foo'",
            ["-b"], {'action': 'foo'})

    def test_type_invalid(self):
        self.assertOptionError(
            "option -b: invalid option type: 'foo'",
            ["-b"], {'type': 'foo'})
        self.assertOptionError(
            "option -b: invalid option type: 'tuple'",
            ["-b"], {'type': tuple})

    def test_no_type_for_action(self):
        self.assertOptionError(
            "option -b: must not supply a type for action 'count'",
            ["-b"], {'action': 'count', 'type': 'int'})

    def test_no_choices_list(self):
        self.assertOptionError(
            "option -b/--bad: must supply a list of "
            "choices for type 'choice'",
            ["-b", "--bad"], {'type': "choice"})

    def test_bad_choices_list(self):
        typename = type('').__name__
        self.assertOptionError(
            "option -b/--bad: choices must be a list of "
            "strings ('%s' supplied)" % typename,
            ["-b", "--bad"],
            {'type': "choice", 'choices':"bad choices"})

    def test_no_choices_for_type(self):
        self.assertOptionError(
            "option -b: must not supply choices for type 'int'",
            ["-b"], {'type': 'int', 'choices':"bad"})

    def test_no_const_for_action(self):
        self.assertOptionError(
            "option -b: 'const' must not be supplied for action 'store'",
            ["-b"], {'action': 'store', 'const': 1})

    def test_no_nargs_for_action(self):
        self.assertOptionError(
            "option -b: 'nargs' must not be supplied for action 'count'",
            ["-b"], {'action': 'count', 'nargs': 2})

    def test_callback_not_callable(self):
        self.assertOptionError(
            "option -b: callback not callable: 'foo'",
            ["-b"], {'action': 'callback',
                     'callback': 'foo'})

    def dummy(self):
        pass

    def test_callback_args_no_tuple(self):
        self.assertOptionError(
            "option -b: callback_args, if supplied, "
            "must be a tuple: not 'foo'",
            ["-b"], {'action': 'callback',
                     'callback': self.dummy,
                     'callback_args': 'foo'})

    def test_callback_kwargs_no_dict(self):
        self.assertOptionError(
            "option -b: callback_kwargs, if supplied, "
            "must be a dict: not 'foo'",
            ["-b"], {'action': 'callback',
                     'callback': self.dummy,
                     'callback_kwargs': 'foo'})

    def test_no_callback_for_action(self):
        self.assertOptionError(
            "option -b: callback supplied ('foo') for non-callback option",
            ["-b"], {'action': 'store',
                     'callback': 'foo'})

    def test_no_callback_args_for_action(self):
        self.assertOptionError(
            "option -b: callback_args supplied for non-callback option",
            ["-b"], {'action': 'store',
                     'callback_args': 'foo'})

    def test_no_callback_kwargs_for_action(self):
        self.assertOptionError(
            "option -b: callback_kwargs supplied for non-callback option",
            ["-b"], {'action': 'store',
                     'callback_kwargs': 'foo'})

    def test_no_single_dash(self):
        self.assertOptionError(
            "invalid long option string '-debug': "
            "must start with --, followed by non-dash",
            ["-debug"])

        self.assertOptionError(
            "option -d: invalid long option string '-debug': must start with"
            " --, followed by non-dash",
            ["-d", "-debug"])

        self.assertOptionError(
            "invalid long option string '-debug': "
            "must start with --, followed by non-dash",
            ["-debug", "--debug"])

class TestOptionParser(BaseTest):
    def setUp(self):
        self.parser = OptionParser()
        self.parser.add_option("-v", "--verbose", "-n", "--noisy",
                          action="store_true", dest="verbose")
        self.parser.add_option("-q", "--quiet", "--silent",
                          action="store_false", dest="verbose")

    def test_add_option_no_Option(self):
        self.assertTypeError(self.parser.add_option,
                             "not an Option instance: None", None)

    def test_add_option_invalid_arguments(self):
        self.assertTypeError(self.parser.add_option,
                             "invalid arguments", None, None)

    def test_get_option(self):
        opt1 = self.parser.get_option("-v")
        self.assertIsInstance(opt1, Option)
        self.assertEqual(opt1._short_opts, ["-v", "-n"])
        self.assertEqual(opt1._long_opts, ["--verbose", "--noisy"])
        self.assertEqual(opt1.action, "store_true")
        self.assertEqual(opt1.dest, "verbose")

    def test_get_option_equals(self):
        opt1 = self.parser.get_option("-v")
        opt2 = self.parser.get_option("--verbose")
        opt3 = self.parser.get_option("-n")
        opt4 = self.parser.get_option("--noisy")
        self.assertTrue(opt1 is opt2 is opt3 is opt4)

    def test_has_option(self):
        self.assertTrue(self.parser.has_option("-v"))
        self.assertTrue(self.parser.has_option("--verbose"))

    def assertTrueremoved(self):
        self.assertTrue(self.parser.get_option("-v") is None)
        self.assertTrue(self.parser.get_option("--verbose") is None)
        self.assertTrue(self.parser.get_option("-n") is None)
        self.assertTrue(self.parser.get_option("--noisy") is None)

        self.assertFalse(self.parser.has_option("-v"))
        self.assertFalse(self.parser.has_option("--verbose"))
        self.assertFalse(self.parser.has_option("-n"))
        self.assertFalse(self.parser.has_option("--noisy"))

        self.assertTrue(self.parser.has_option("-q"))
        self.assertTrue(self.parser.has_option("--silent"))

    def test_remove_short_opt(self):
        self.parser.remove_option("-n")
        self.assertTrueremoved()

    def test_remove_long_opt(self):
        self.parser.remove_option("--verbose")
        self.assertTrueremoved()

    def test_remove_nonexistent(self):
        self.assertRaises(self.parser.remove_option, ('foo',), None,
                          ValueError, "no such option 'foo'")

    @support.impl_detail('Relies on sys.getrefcount', cpython=True)
    def test_refleak(self):
        # If an OptionParser is carrying around a reference to a large
        # object, various cycles can prevent it from being GC'd in
        # a timely fashion.  destroy() breaks the cycles to ensure stuff
        # can be cleaned up.
        big_thing = [42]
        refcount = sys.getrefcount(big_thing)
        parser = OptionParser()
        parser.add_option("-a", "--aaarggh")
        parser.big_thing = big_thing

        parser.destroy()
        #self.assertEqual(refcount, sys.getrefcount(big_thing))
        del parser
        self.assertEqual(refcount, sys.getrefcount(big_thing))


class TestOptionValues(BaseTest):
    def setUp(self):
        pass

    def test_basics(self):
        values = Values()
        self.assertEqual(vars(values), {})
        self.assertEqual(values, {})
        self.assertNotEqual(values, {"foo": "bar"})
        self.assertNotEqual(values, "")

        dict = {"foo": "bar", "baz": 42}
        values = Values(defaults=dict)
        self.assertEqual(vars(values), dict)
        self.assertEqual(values, dict)
        self.assertNotEqual(values, {"foo": "bar"})
        self.assertNotEqual(values, {})
        self.assertNotEqual(values, "")
        self.assertNotEqual(values, [])


class TestTypeAliases(BaseTest):
    def setUp(self):
        self.parser = OptionParser()

    def test_str_aliases_string(self):
        self.parser.add_option("-s", type="str")
        self.assertEqual(self.parser.get_option("-s").type, "string")

    def test_type_object(self):
        self.parser.add_option("-s", type=str)
        self.assertEqual(self.parser.get_option("-s").type, "string")
        self.parser.add_option("-x", type=int)
        self.assertEqual(self.parser.get_option("-x").type, "int")


# Custom type for testing processing of default values.
_time_units = { 's' : 1, 'm' : 60, 'h' : 60*60, 'd' : 60*60*24 }

def _check_duration(option, opt, value):
    try:
        if value[-1].isdigit():
            return int(value)
        else:
            return int(value[:-1]) * _time_units[value[-1]]
    except (ValueError, IndexError):
        raise OptionValueError(
            'option %s: invalid duration: %r' % (opt, value))

class DurationOption(Option):
    TYPES = Option.TYPES + ('duration',)
    TYPE_CHECKER = copy.copy(Option.TYPE_CHECKER)
    TYPE_CHECKER['duration'] = _check_duration

class TestDefaultValues(BaseTest):
    def setUp(self):
        self.parser = OptionParser()
        self.parser.add_option("-v", "--verbose", default=True)
        self.parser.add_option("-q", "--quiet", dest='verbose')
        self.parser.add_option("-n", type="int", default=37)
        self.parser.add_option("-m", type="int")
        self.parser.add_option("-s", default="foo")
        self.parser.add_option("-t")
        self.parser.add_option("-u", default=None)
        self.expected = { 'verbose': True,
                          'n': 37,
                          'm': None,
                          's': "foo",
                          't': None,
                          'u': None }

    def test_basic_defaults(self):
        self.assertEqual(self.parser.get_default_values(), self.expected)

    def test_mixed_defaults_post(self):
        self.parser.set_defaults(n=42, m=-100)
        self.expected.update({'n': 42, 'm': -100})
        self.assertEqual(self.parser.get_default_values(), self.expected)

    def test_mixed_defaults_pre(self):
        self.parser.set_defaults(x="barf", y="blah")
        self.parser.add_option("-x", default="frob")
        self.parser.add_option("-y")

        self.expected.update({'x': "frob", 'y': "blah"})
        self.assertEqual(self.parser.get_default_values(), self.expected)

        self.parser.remove_option("-y")
        self.parser.add_option("-y", default=None)
        self.expected.update({'y': None})
        self.assertEqual(self.parser.get_default_values(), self.expected)

    def test_process_default(self):
        self.parser.option_class = DurationOption
        self.parser.add_option("-d", type="duration", default=300)
        self.parser.add_option("-e", type="duration", default="6m")
        self.parser.set_defaults(n="42")
        self.expected.update({'d': 300, 'e': 360, 'n': 42})
        self.assertEqual(self.parser.get_default_values(), self.expected)

        self.parser.set_process_default_values(False)
        self.expected.update({'d': 300, 'e': "6m", 'n': "42"})
        self.assertEqual(self.parser.get_default_values(), self.expected)


class TestProgName(BaseTest):
    """
    Test that %prog expands to the right thing in usage, version,
    and help strings.
    """

    def assertUsage(self, parser, expected_usage):
        self.assertEqual(parser.get_usage(), expected_usage)

    def assertVersion(self, parser, expected_version):
        self.assertEqual(parser.get_version(), expected_version)


    def test_default_progname(self):
        # Make sure that program name taken from sys.argv[0] by default.
        save_argv = sys.argv[:]
        try:
            sys.argv[0] = os.path.join("foo", "bar", "baz.py")
            parser = OptionParser("%prog ...", version="%prog 1.2")
            expected_usage = "Usage: baz.py ...\n"
            self.assertUsage(parser, expected_usage)
            self.assertVersion(parser, "baz.py 1.2")
            self.assertHelp(parser,
                            expected_usage + "\n" +
                            "Options:\n"
                            "  --version   show program's version number and exit\n"
                            "  -h, --help  show this help message and exit\n")
        finally:
            sys.argv[:] = save_argv

    def test_custom_progname(self):
        parser = OptionParser(prog="thingy",
                              version="%prog 0.1",
                              usage="%prog arg arg")
        parser.remove_option("-h")
        parser.remove_option("--version")
        expected_usage = "Usage: thingy arg arg\n"
        self.assertUsage(parser, expected_usage)
        self.assertVersion(parser, "thingy 0.1")
        self.assertHelp(parser, expected_usage + "\n")


class TestExpandDefaults(BaseTest):
    def setUp(self):
        self.parser = OptionParser(prog="test")
        self.help_prefix = """\
Usage: test [options]

Options:
  -h, --help            show this help message and exit
"""
        self.file_help = "read from FILE [default: %default]"
        self.expected_help_file = self.help_prefix + \
            "  -f FILE, --file=FILE  read from FILE [default: foo.txt]\n"
        self.expected_help_none = self.help_prefix + \
            "  -f FILE, --file=FILE  read from FILE [default: none]\n"

    def test_option_default(self):
        self.parser.add_option("-f", "--file",
                               default="foo.txt",
                               help=self.file_help)
        self.assertHelp(self.parser, self.expected_help_file)

    def test_parser_default_1(self):
        self.parser.add_option("-f", "--file",
                               help=self.file_help)
        self.parser.set_default('file', "foo.txt")
        self.assertHelp(self.parser, self.expected_help_file)

    def test_parser_default_2(self):
        self.parser.add_option("-f", "--file",
                               help=self.file_help)
        self.parser.set_defaults(file="foo.txt")
        self.assertHelp(self.parser, self.expected_help_file)

    def test_no_default(self):
        self.parser.add_option("-f", "--file",
                               help=self.file_help)
        self.assertHelp(self.parser, self.expected_help_none)

    def test_default_none_1(self):
        self.parser.add_option("-f", "--file",
                               default=None,
                               help=self.file_help)
        self.assertHelp(self.parser, self.expected_help_none)

    def test_default_none_2(self):
        self.parser.add_option("-f", "--file",
                               help=self.file_help)
        self.parser.set_defaults(file=None)
        self.assertHelp(self.parser, self.expected_help_none)

    def test_float_default(self):
        self.parser.add_option(
            "-p", "--prob",
            help="blow up with probability PROB [default: %default]")
        self.parser.set_defaults(prob=0.43)
        expected_help = self.help_prefix + \
            "  -p PROB, --prob=PROB  blow up with probability PROB [default: 0.43]\n"
        self.assertHelp(self.parser, expected_help)

    def test_alt_expand(self):
        self.parser.add_option("-f", "--file",
                               default="foo.txt",
                               help="read from FILE [default: *DEFAULT*]")
        self.parser.formatter.default_tag = "*DEFAULT*"
        self.assertHelp(self.parser, self.expected_help_file)

    def test_no_expand(self):
        self.parser.add_option("-f", "--file",
                               default="foo.txt",
                               help="read from %default file")
        self.parser.formatter.default_tag = None
        expected_help = self.help_prefix + \
            "  -f FILE, --file=FILE  read from %default file\n"
        self.assertHelp(self.parser, expected_help)


# -- Test parser.parse_args() ------------------------------------------

class TestStandard(BaseTest):
    def setUp(self):
        options = [make_option("-a", type="string"),
                   make_option("-b", "--boo", type="int", dest='boo'),
                   make_option("--foo", action="append")]

        self.parser = InterceptingOptionParser(usage=SUPPRESS_USAGE,
                                               option_list=options)

    def test_required_value(self):
        self.assertParseFail(["-a"], "-a option requires 1 argument")

    def test_invalid_integer(self):
        self.assertParseFail(["-b", "5x"],
                             "option -b: invalid integer value: '5x'")

    def test_no_such_option(self):
        self.assertParseFail(["--boo13"], "no such option: --boo13")

    def test_long_invalid_integer(self):
        self.assertParseFail(["--boo=x5"],
                             "option --boo: invalid integer value: 'x5'")

    def test_empty(self):
        self.assertParseOK([], {'a': None, 'boo': None, 'foo': None}, [])

    def test_shortopt_empty_longopt_append(self):
        self.assertParseOK(["-a", "", "--foo=blah", "--foo="],
                           {'a': "", 'boo': None, 'foo': ["blah", ""]},
                           [])

    def test_long_option_append(self):
        self.assertParseOK(["--foo", "bar", "--foo", "", "--foo=x"],
                           {'a': None,
                            'boo': None,
                            'foo': ["bar", "", "x"]},
                           [])

    def test_option_argument_joined(self):
        self.assertParseOK(["-abc"],
                           {'a': "bc", 'boo': None, 'foo': None},
                           [])

    def test_option_argument_split(self):
        self.assertParseOK(["-a", "34"],
                           {'a': "34", 'boo': None, 'foo': None},
                           [])

    def test_option_argument_joined_integer(self):
        self.assertParseOK(["-b34"],
                           {'a': None, 'boo': 34, 'foo': None},
                           [])

    def test_option_argument_split_negative_integer(self):
        self.assertParseOK(["-b", "-5"],
                           {'a': None, 'boo': -5, 'foo': None},
                           [])

    def test_long_option_argument_joined(self):
        self.assertParseOK(["--boo=13"],
                           {'a': None, 'boo': 13, 'foo': None},
                           [])

    def test_long_option_argument_split(self):
        self.assertParseOK(["--boo", "111"],
                           {'a': None, 'boo': 111, 'foo': None},
                           [])

    def test_long_option_short_option(self):
        self.assertParseOK(["--foo=bar", "-axyz"],
                           {'a': 'xyz', 'boo': None, 'foo': ["bar"]},
                           [])

    def test_abbrev_long_option(self):
        self.assertParseOK(["--f=bar", "-axyz"],
                           {'a': 'xyz', 'boo': None, 'foo': ["bar"]},
                           [])

    def test_defaults(self):
        (options, args) = self.parser.parse_args([])
        defaults = self.parser.get_default_values()
        self.assertEqual(vars(defaults), vars(options))

    def test_ambiguous_option(self):
        self.parser.add_option("--foz", action="store",
                               type="string", dest="foo")
        self.assertParseFail(["--f=bar"],
                             "ambiguous option: --f (--foo, --foz?)")


    def test_short_and_long_option_split(self):
        self.assertParseOK(["-a", "xyz", "--foo", "bar"],
                           {'a': 'xyz', 'boo': None, 'foo': ["bar"]},
                           [])

    def test_short_option_split_long_option_append(self):
        self.assertParseOK(["--foo=bar", "-b", "123", "--foo", "baz"],
                           {'a': None, 'boo': 123, 'foo': ["bar", "baz"]},
                           [])

    def test_short_option_split_one_positional_arg(self):
        self.assertParseOK(["-a", "foo", "bar"],
                           {'a': "foo", 'boo': None, 'foo': None},
                           ["bar"])

    def test_short_option_consumes_separator(self):
        self.assertParseOK(["-a", "--", "foo", "bar"],
                           {'a': "--", 'boo': None, 'foo': None},
                           ["foo", "bar"])
        self.assertParseOK(["-a", "--", "--foo", "bar"],
                           {'a': "--", 'boo': None, 'foo': ["bar"]},
                           [])

    def test_short_option_joined_and_separator(self):
        self.assertParseOK(["-ab", "--", "--foo", "bar"],
                           {'a': "b", 'boo': None, 'foo': None},
                           ["--foo", "bar"]),

    def test_hyphen_becomes_positional_arg(self):
        self.assertParseOK(["-ab", "-", "--foo", "bar"],
                           {'a': "b", 'boo': None, 'foo': ["bar"]},
                           ["-"])

    def test_no_append_versus_append(self):
        self.assertParseOK(["-b3", "-b", "5", "--foo=bar", "--foo", "baz"],
                           {'a': None, 'boo': 5, 'foo': ["bar", "baz"]},
                           [])

    def test_option_consumes_optionlike_string(self):
        self.assertParseOK(["-a", "-b3"],
                           {'a': "-b3", 'boo': None, 'foo': None},
                           [])

    def test_combined_single_invalid_option(self):
        self.parser.add_option("-t", action="store_true")
        self.assertParseFail(["-test"],
                             "no such option: -e")

class TestBool(BaseTest):
    def setUp(self):
        options = [make_option("-v",
                               "--verbose",
                               action="store_true",
                               dest="verbose",
                               default=''),
                   make_option("-q",
                               "--quiet",
                               action="store_false",
                               dest="verbose")]
        self.parser = OptionParser(option_list = options)

    def test_bool_default(self):
        self.assertParseOK([],
                           {'verbose': ''},
                           [])

    def test_bool_false(self):
        (options, args) = self.assertParseOK(["-q"],
                                             {'verbose': 0},
                                             [])
        self.assertTrue(options.verbose is False)

    def test_bool_true(self):
        (options, args) = self.assertParseOK(["-v"],
                                             {'verbose': 1},
                                             [])
        self.assertTrue(options.verbose is True)

    def test_bool_flicker_on_and_off(self):
        self.assertParseOK(["-qvq", "-q", "-v"],
                           {'verbose': 1},
                           [])

class TestChoice(BaseTest):
    def setUp(self):
        self.parser = InterceptingOptionParser(usage=SUPPRESS_USAGE)
        self.parser.add_option("-c", action="store", type="choice",
                               dest="choice", choices=["one", "two", "three"])

    def test_valid_choice(self):
        self.assertParseOK(["-c", "one", "xyz"],
                           {'choice': 'one'},
                           ["xyz"])

    def test_invalid_choice(self):
        self.assertParseFail(["-c", "four", "abc"],
                             "option -c: invalid choice: 'four' "
                             "(choose from 'one', 'two', 'three')")

    def test_add_choice_option(self):
        self.parser.add_option("-d", "--default",
                               choices=["four", "five", "six"])
        opt = self.parser.get_option("-d")
        self.assertEqual(opt.type, "choice")
        self.assertEqual(opt.action, "store")

class TestCount(BaseTest):
    def setUp(self):
        self.parser = InterceptingOptionParser(usage=SUPPRESS_USAGE)
        self.v_opt = make_option("-v", action="count", dest="verbose")
        self.parser.add_option(self.v_opt)
        self.parser.add_option("--verbose", type="int", dest="verbose")
        self.parser.add_option("-q", "--quiet",
                               action="store_const", dest="verbose", const=0)

    def test_empty(self):
        self.assertParseOK([], {'verbose': None}, [])

    def test_count_one(self):
        self.assertParseOK(["-v"], {'verbose': 1}, [])

    def test_count_three(self):
        self.assertParseOK(["-vvv"], {'verbose': 3}, [])

    def test_count_three_apart(self):
        self.assertParseOK(["-v", "-v", "-v"], {'verbose': 3}, [])

    def test_count_override_amount(self):
        self.assertParseOK(["-vvv", "--verbose=2"], {'verbose': 2}, [])

    def test_count_override_quiet(self):
        self.assertParseOK(["-vvv", "--verbose=2", "-q"], {'verbose': 0}, [])

    def test_count_overriding(self):
        self.assertParseOK(["-vvv", "--verbose=2", "-q", "-v"],
                           {'verbose': 1}, [])

    def test_count_interspersed_args(self):
        self.assertParseOK(["--quiet", "3", "-v"],
                           {'verbose': 1},
                           ["3"])

    def test_count_no_interspersed_args(self):
        self.parser.disable_interspersed_args()
        self.assertParseOK(["--quiet", "3", "-v"],
                           {'verbose': 0},
                           ["3", "-v"])

    def test_count_no_such_option(self):
        self.assertParseFail(["-q3", "-v"], "no such option: -3")

    def test_count_option_no_value(self):
        self.assertParseFail(["--quiet=3", "-v"],
                             "--quiet option does not take a value")

    def test_count_with_default(self):
        self.parser.set_default('verbose', 0)
        self.assertParseOK([], {'verbose':0}, [])

    def test_count_overriding_default(self):
        self.parser.set_default('verbose', 0)
        self.assertParseOK(["-vvv", "--verbose=2", "-q", "-v"],
                           {'verbose': 1}, [])

class TestMultipleArgs(BaseTest):
    def setUp(self):
        self.parser = InterceptingOptionParser(usage=SUPPRESS_USAGE)
        self.parser.add_option("-p", "--point",
                               action="store", nargs=3, type="float", dest="point")

    def test_nargs_with_positional_args(self):
        self.assertParseOK(["foo", "-p", "1", "2.5", "-4.3", "xyz"],
                           {'point': (1.0, 2.5, -4.3)},
                           ["foo", "xyz"])

    def test_nargs_long_opt(self):
        self.assertParseOK(["--point", "-1", "2.5", "-0", "xyz"],
                           {'point': (-1.0, 2.5, -0.0)},
                           ["xyz"])

    def test_nargs_invalid_float_value(self):
        self.assertParseFail(["-p", "1.0", "2x", "3.5"],
                             "option -p: "
                             "invalid floating-point value: '2x'")

    def test_nargs_required_values(self):
        self.assertParseFail(["--point", "1.0", "3.5"],
                             "--point option requires 3 arguments")

class TestMultipleArgsAppend(BaseTest):
    def setUp(self):
        self.parser = InterceptingOptionParser(usage=SUPPRESS_USAGE)
        self.parser.add_option("-p", "--point", action="store", nargs=3,
                               type="float", dest="point")
        self.parser.add_option("-f", "--foo", action="append", nargs=2,
                               type="int", dest="foo")
        self.parser.add_option("-z", "--zero", action="append_const",
                               dest="foo", const=(0, 0))

    def test_nargs_append(self):
        self.assertParseOK(["-f", "4", "-3", "blah", "--foo", "1", "666"],
                           {'point': None, 'foo': [(4, -3), (1, 666)]},
                           ["blah"])

    def test_nargs_append_required_values(self):
        self.assertParseFail(["-f4,3"],
                             "-f option requires 2 arguments")

    def test_nargs_append_simple(self):
        self.assertParseOK(["--foo=3", "4"],
                           {'point': None, 'foo':[(3, 4)]},
                           [])

    def test_nargs_append_const(self):
        self.assertParseOK(["--zero", "--foo", "3", "4", "-z"],
                           {'point': None, 'foo':[(0, 0), (3, 4), (0, 0)]},
                           [])

class TestVersion(BaseTest):
    def test_version(self):
        self.parser = InterceptingOptionParser(usage=SUPPRESS_USAGE,
                                               version="%prog 0.1")
        save_argv = sys.argv[:]
        try:
            sys.argv[0] = os.path.join(os.curdir, "foo", "bar")
            self.assertOutput(["--version"], "bar 0.1\n")
        finally:
            sys.argv[:] = save_argv

    def test_no_version(self):
        self.parser = InterceptingOptionParser(usage=SUPPRESS_USAGE)
        self.assertParseFail(["--version"],
                             "no such option: --version")

# -- Test conflicting default values and parser.parse_args() -----------

class TestConflictingDefaults(BaseTest):
    """Conflicting default values: the last one should win."""
    def setUp(self):
        self.parser = OptionParser(option_list=[
            make_option("-v", action="store_true", dest="verbose", default=1)])

    def test_conflict_default(self):
        self.parser.add_option("-q", action="store_false", dest="verbose",
                               default=0)
        self.assertParseOK([], {'verbose': 0}, [])

    def test_conflict_default_none(self):
        self.parser.add_option("-q", action="store_false", dest="verbose",
                               default=None)
        self.assertParseOK([], {'verbose': None}, [])

class TestOptionGroup(BaseTest):
    def setUp(self):
        self.parser = OptionParser(usage=SUPPRESS_USAGE)

    def test_option_group_create_instance(self):
        group = OptionGroup(self.parser, "Spam")
        self.parser.add_option_group(group)
        group.add_option("--spam", action="store_true",
                         help="spam spam spam spam")
        self.assertParseOK(["--spam"], {'spam': 1}, [])

    def test_add_group_no_group(self):
        self.assertTypeError(self.parser.add_option_group,
                             "not an OptionGroup instance: None", None)

    def test_add_group_invalid_arguments(self):
        self.assertTypeError(self.parser.add_option_group,
                             "invalid arguments", None, None)

    def test_add_group_wrong_parser(self):
        group = OptionGroup(self.parser, "Spam")
        group.parser = OptionParser()
        self.assertRaises(self.parser.add_option_group, (group,), None,
                          ValueError, "invalid OptionGroup (wrong parser)")

    def test_group_manipulate(self):
        group = self.parser.add_option_group("Group 2",
                                             description="Some more options")
        group.set_title("Bacon")
        group.add_option("--bacon", type="int")
        self.assertTrue(self.parser.get_option_group("--bacon"), group)

# -- Test extending and parser.parse_args() ----------------------------

class TestExtendAddTypes(BaseTest):
    def setUp(self):
        self.parser = InterceptingOptionParser(usage=SUPPRESS_USAGE,
                                               option_class=self.MyOption)
        self.parser.add_option("-a", None, type="string", dest="a")
        self.parser.add_option("-f", "--file", type="file", dest="file")

    def tearDown(self):
        if os.path.isdir(os_helper.TESTFN):
            os.rmdir(os_helper.TESTFN)
        elif os.path.isfile(os_helper.TESTFN):
            os.unlink(os_helper.TESTFN)

    class MyOption (Option):
        def check_file(option, opt, value):
            if not os.path.exists(value):
                raise OptionValueError("%s: file does not exist" % value)
            elif not os.path.isfile(value):
                raise OptionValueError("%s: not a regular file" % value)
            return value

        TYPES = Option.TYPES + ("file",)
        TYPE_CHECKER = copy.copy(Option.TYPE_CHECKER)
        TYPE_CHECKER["file"] = check_file

    def test_filetype_ok(self):
        os_helper.create_empty_file(os_helper.TESTFN)
        self.assertParseOK(["--file", os_helper.TESTFN, "-afoo"],
                           {'file': os_helper.TESTFN, 'a': 'foo'},
                           [])

    def test_filetype_noexist(self):
        self.assertParseFail(["--file", os_helper.TESTFN, "-afoo"],
                             "%s: file does not exist" %
                             os_helper.TESTFN)

    def test_filetype_notfile(self):
        os.mkdir(os_helper.TESTFN)
        self.assertParseFail(["--file", os_helper.TESTFN, "-afoo"],
                             "%s: not a regular file" %
                             os_helper.TESTFN)


class TestExtendAddActions(BaseTest):
    def setUp(self):
        options = [self.MyOption("-a", "--apple", action="extend",
                                 type="string", dest="apple")]
        self.parser = OptionParser(option_list=options)

    class MyOption (Option):
        ACTIONS = Option.ACTIONS + ("extend",)
        STORE_ACTIONS = Option.STORE_ACTIONS + ("extend",)
        TYPED_ACTIONS = Option.TYPED_ACTIONS + ("extend",)

        def take_action(self, action, dest, opt, value, values, parser):
            if action == "extend":
                lvalue = value.split(",")
                values.ensure_value(dest, []).extend(lvalue)
            else:
                Option.take_action(self, action, dest, opt, parser, value,
                                   values)

    def test_extend_add_action(self):
        self.assertParseOK(["-afoo,bar", "--apple=blah"],
                           {'apple': ["foo", "bar", "blah"]},
                           [])

    def test_extend_add_action_normal(self):
        self.assertParseOK(["-a", "foo", "-abar", "--apple=x,y"],
                           {'apple': ["foo", "bar", "x", "y"]},
                           [])

# -- Test callbacks and parser.parse_args() ----------------------------

class TestCallback(BaseTest):
    def setUp(self):
        options = [make_option("-x",
                               None,
                               action="callback",
                               callback=self.process_opt),
                   make_option("-f",
                               "--file",
                               action="callback",
                               callback=self.process_opt,
                               type="string",
                               dest="filename")]
        self.parser = OptionParser(option_list=options)

    def process_opt(self, option, opt, value, parser_):
        if opt == "-x":
            self.assertEqual(option._short_opts, ["-x"])
            self.assertEqual(option._long_opts, [])
            self.assertTrue(parser_ is self.parser)
            self.assertTrue(value is None)
            self.assertEqual(vars(parser_.values), {'filename': None})

            parser_.values.x = 42
        elif opt == "--file":
            self.assertEqual(option._short_opts, ["-f"])
            self.assertEqual(option._long_opts, ["--file"])
            self.assertTrue(parser_ is self.parser)
            self.assertEqual(value, "foo")
            self.assertEqual(vars(parser_.values), {'filename': None, 'x': 42})

            setattr(parser_.values, option.dest, value)
        else:
            self.fail("Unknown option %r in process_opt." % opt)

    def test_callback(self):
        self.assertParseOK(["-x", "--file=foo"],
                           {'filename': "foo", 'x': 42},
                           [])

    def test_callback_help(self):
        # This test was prompted by SF bug #960515 -- the point is
        # not to inspect the help text, just to make sure that
        # format_help() doesn't crash.
        parser = OptionParser(usage=SUPPRESS_USAGE)
        parser.remove_option("-h")
        parser.add_option("-t", "--test", action="callback",
                          callback=lambda: None, type="string",
                          help="foo")

        expected_help = ("Options:\n"
                         "  -t TEST, --test=TEST  foo\n")
        self.assertHelp(parser, expected_help)


class TestCallbackExtraArgs(BaseTest):
    def setUp(self):
        options = [make_option("-p", "--point", action="callback",
                               callback=self.process_tuple,
                               callback_args=(3, int), type="string",
                               dest="points", default=[])]
        self.parser = OptionParser(option_list=options)

    def process_tuple(self, option, opt, value, parser_, len, type):
        self.assertEqual(len, 3)
        self.assertTrue(type is int)

        if opt == "-p":
            self.assertEqual(value, "1,2,3")
        elif opt == "--point":
            self.assertEqual(value, "4,5,6")

        value = tuple(map(type, value.split(",")))
        getattr(parser_.values, option.dest).append(value)

    def test_callback_extra_args(self):
        self.assertParseOK(["-p1,2,3", "--point", "4,5,6"],
                           {'points': [(1,2,3), (4,5,6)]},
                           [])

class TestCallbackMeddleArgs(BaseTest):
    def setUp(self):
        options = [make_option(str(x), action="callback",
                               callback=self.process_n, dest='things')
                   for x in range(-1, -6, -1)]
        self.parser = OptionParser(option_list=options)

    # Callback that meddles in rargs, largs
    def process_n(self, option, opt, value, parser_):
        # option is -3, -5, etc.
        nargs = int(opt[1:])
        rargs = parser_.rargs
        if len(rargs) < nargs:
            self.fail("Expected %d arguments for %s option." % (nargs, opt))
        dest = parser_.values.ensure_value(option.dest, [])
        dest.append(tuple(rargs[0:nargs]))
        parser_.largs.append(nargs)
        del rargs[0:nargs]

    def test_callback_meddle_args(self):
        self.assertParseOK(["-1", "foo", "-3", "bar", "baz", "qux"],
                           {'things': [("foo",), ("bar", "baz", "qux")]},
                           [1, 3])

    def test_callback_meddle_args_separator(self):
        self.assertParseOK(["-2", "foo", "--"],
                           {'things': [('foo', '--')]},
                           [2])

class TestCallbackManyArgs(BaseTest):
    def setUp(self):
        options = [make_option("-a", "--apple", action="callback", nargs=2,
                               callback=self.process_many, type="string"),
                   make_option("-b", "--bob", action="callback", nargs=3,
                               callback=self.process_many, type="int")]
        self.parser = OptionParser(option_list=options)

    def process_many(self, option, opt, value, parser_):
        if opt == "-a":
            self.assertEqual(value, ("foo", "bar"))
        elif opt == "--apple":
            self.assertEqual(value, ("ding", "dong"))
        elif opt == "-b":
            self.assertEqual(value, (1, 2, 3))
        elif opt == "--bob":
            self.assertEqual(value, (-666, 42, 0))

    def test_many_args(self):
        self.assertParseOK(["-a", "foo", "bar", "--apple", "ding", "dong",
                            "-b", "1", "2", "3", "--bob", "-666", "42",
                            "0"],
                           {"apple": None, "bob": None},
                           [])

class TestCallbackCheckAbbrev(BaseTest):
    def setUp(self):
        self.parser = OptionParser()
        self.parser.add_option("--foo-bar", action="callback",
                               callback=self.check_abbrev)

    def check_abbrev(self, option, opt, value, parser):
        self.assertEqual(opt, "--foo-bar")

    def test_abbrev_callback_expansion(self):
        self.assertParseOK(["--foo"], {}, [])

class TestCallbackVarArgs(BaseTest):
    def setUp(self):
        options = [make_option("-a", type="int", nargs=2, dest="a"),
                   make_option("-b", action="store_true", dest="b"),
                   make_option("-c", "--callback", action="callback",
                               callback=self.variable_args, dest="c")]
        self.parser = InterceptingOptionParser(usage=SUPPRESS_USAGE,
                                               option_list=options)

    def variable_args(self, option, opt, value, parser):
        self.assertTrue(value is None)
        value = []
        rargs = parser.rargs
        while rargs:
            arg = rargs[0]
            if ((arg[:2] == "--" and len(arg) > 2) or
                (arg[:1] == "-" and len(arg) > 1 and arg[1] != "-")):
                break
            else:
                value.append(arg)
                del rargs[0]
        setattr(parser.values, option.dest, value)

    def test_variable_args(self):
        self.assertParseOK(["-a3", "-5", "--callback", "foo", "bar"],
                           {'a': (3, -5), 'b': None, 'c': ["foo", "bar"]},
                           [])

    def test_consume_separator_stop_at_option(self):
        self.assertParseOK(["-c", "37", "--", "xxx", "-b", "hello"],
                           {'a': None,
                            'b': True,
                            'c': ["37", "--", "xxx"]},
                           ["hello"])

    def test_positional_arg_and_variable_args(self):
        self.assertParseOK(["hello", "-c", "foo", "-", "bar"],
                           {'a': None,
                            'b': None,
                            'c':["foo", "-", "bar"]},
                           ["hello"])

    def test_stop_at_option(self):
        self.assertParseOK(["-c", "foo", "-b"],
                           {'a': None, 'b': True, 'c': ["foo"]},
                           [])

    def test_stop_at_invalid_option(self):
        self.assertParseFail(["-c", "3", "-5", "-a"], "no such option: -5")


# -- Test conflict handling and parser.parse_args() --------------------

class ConflictBase(BaseTest):
    def setUp(self):
        options = [make_option("-v", "--verbose", action="count",
                               dest="verbose", help="increment verbosity")]
        self.parser = InterceptingOptionParser(usage=SUPPRESS_USAGE,
                                               option_list=options)

    def show_version(self, option, opt, value, parser):
        parser.values.show_version = 1

class TestConflict(ConflictBase):
    """Use the default conflict resolution for Optik 1.2: error."""
    def assertTrueconflict_error(self, func):
        err = self.assertRaises(
            func, ("-v", "--version"), {'action' : "callback",
                                        'callback' : self.show_version,
                                        'help' : "show version"},
            OptionConflictError,
            "option -v/--version: conflicting option string(s): -v")

        self.assertEqual(err.msg, "conflicting option string(s): -v")
        self.assertEqual(err.option_id, "-v/--version")

    def test_conflict_error(self):
        self.assertTrueconflict_error(self.parser.add_option)

    def test_conflict_error_group(self):
        group = OptionGroup(self.parser, "Group 1")
        self.assertTrueconflict_error(group.add_option)

    def test_no_such_conflict_handler(self):
        self.assertRaises(
            self.parser.set_conflict_handler, ('foo',), None,
            ValueError, "invalid conflict_resolution value 'foo'")


class TestConflictResolve(ConflictBase):
    def setUp(self):
        ConflictBase.setUp(self)
        self.parser.set_conflict_handler("resolve")
        self.parser.add_option("-v", "--version", action="callback",
                               callback=self.show_version, help="show version")

    def test_conflict_resolve(self):
        v_opt = self.parser.get_option("-v")
        verbose_opt = self.parser.get_option("--verbose")
        version_opt = self.parser.get_option("--version")

        self.assertTrue(v_opt is version_opt)
        self.assertTrue(v_opt is not verbose_opt)
        self.assertEqual(v_opt._long_opts, ["--version"])
        self.assertEqual(version_opt._short_opts, ["-v"])
        self.assertEqual(version_opt._long_opts, ["--version"])
        self.assertEqual(verbose_opt._short_opts, [])
        self.assertEqual(verbose_opt._long_opts, ["--verbose"])

    def test_conflict_resolve_help(self):
        self.assertOutput(["-h"], """\
Options:
  --verbose      increment verbosity
  -h, --help     show this help message and exit
  -v, --version  show version
""")

    def test_conflict_resolve_short_opt(self):
        self.assertParseOK(["-v"],
                           {'verbose': None, 'show_version': 1},
                           [])

    def test_conflict_resolve_long_opt(self):
        self.assertParseOK(["--verbose"],
                           {'verbose': 1},
                           [])

    def test_conflict_resolve_long_opts(self):
        self.assertParseOK(["--verbose", "--version"],
                           {'verbose': 1, 'show_version': 1},
                           [])

class TestConflictOverride(BaseTest):
    def setUp(self):
        self.parser = InterceptingOptionParser(usage=SUPPRESS_USAGE)
        self.parser.set_conflict_handler("resolve")
        self.parser.add_option("-n", "--dry-run",
                               action="store_true", dest="dry_run",
                               help="don't do anything")
        self.parser.add_option("--dry-run", "-n",
                               action="store_const", const=42, dest="dry_run",
                               help="dry run mode")

    def test_conflict_override_opts(self):
        opt = self.parser.get_option("--dry-run")
        self.assertEqual(opt._short_opts, ["-n"])
        self.assertEqual(opt._long_opts, ["--dry-run"])

    def test_conflict_override_help(self):
        self.assertOutput(["-h"], """\
Options:
  -h, --help     show this help message and exit
  -n, --dry-run  dry run mode
""")

    def test_conflict_override_args(self):
        self.assertParseOK(["-n"],
                           {'dry_run': 42},
                           [])

# -- Other testing. ----------------------------------------------------

_expected_help_basic = """\
Usage: bar.py [options]

Options:
  -a APPLE           throw APPLEs at basket
  -b NUM, --boo=NUM  shout "boo!" NUM times (in order to frighten away all the
                     evil spirits that cause trouble and mayhem)
  --foo=FOO          store FOO in the foo list for later fooing
  -h, --help         show this help message and exit
"""

_expected_help_long_opts_first = """\
Usage: bar.py [options]

Options:
  -a APPLE           throw APPLEs at basket
  --boo=NUM, -b NUM  shout "boo!" NUM times (in order to frighten away all the
                     evil spirits that cause trouble and mayhem)
  --foo=FOO          store FOO in the foo list for later fooing
  --help, -h         show this help message and exit
"""

_expected_help_title_formatter = """\
Usage
=====
  bar.py [options]

Options
=======
-a APPLE           throw APPLEs at basket
--boo=NUM, -b NUM  shout "boo!" NUM times (in order to frighten away all the
                   evil spirits that cause trouble and mayhem)
--foo=FOO          store FOO in the foo list for later fooing
--help, -h         show this help message and exit
"""

_expected_help_short_lines = """\
Usage: bar.py [options]

Options:
  -a APPLE           throw APPLEs at basket
  -b NUM, --boo=NUM  shout "boo!" NUM times (in order to
                     frighten away all the evil spirits
                     that cause trouble and mayhem)
  --foo=FOO          store FOO in the foo list for later
                     fooing
  -h, --help         show this help message and exit
"""

_expected_very_help_short_lines = """\
Usage: bar.py [options]

Options:
  -a APPLE
    throw
    APPLEs at
    basket
  -b NUM, --boo=NUM
    shout
    "boo!" NUM
    times (in
    order to
    frighten
    away all
    the evil
    spirits
    that cause
    trouble and
    mayhem)
  --foo=FOO
    store FOO
    in the foo
    list for
    later
    fooing
  -h, --help
    show this
    help
    message and
    exit
"""

class TestHelp(BaseTest):
    def setUp(self):
        self.parser = self.make_parser(80)

    def make_parser(self, columns):
        options = [
            make_option("-a", type="string", dest='a',
                        metavar="APPLE", help="throw APPLEs at basket"),
            make_option("-b", "--boo", type="int", dest='boo',
                        metavar="NUM",
                        help=
                        "shout \"boo!\" NUM times (in order to frighten away "
                        "all the evil spirits that cause trouble and mayhem)"),
            make_option("--foo", action="append", type="string", dest='foo',
                        help="store FOO in the foo list for later fooing"),
            ]

        # We need to set COLUMNS for the OptionParser constructor, but
        # we must restore its original value -- otherwise, this test
        # screws things up for other tests when it's part of the Python
        # test suite.
        with os_helper.EnvironmentVarGuard() as env:
            env['COLUMNS'] = str(columns)
            return InterceptingOptionParser(option_list=options)

    def assertHelpEquals(self, expected_output):
        save_argv = sys.argv[:]
        try:
            # Make optparse believe bar.py is being executed.
            sys.argv[0] = os.path.join("foo", "bar.py")
            self.assertOutput(["-h"], expected_output)
        finally:
            sys.argv[:] = save_argv

    def test_help(self):
        self.assertHelpEquals(_expected_help_basic)

    def test_help_old_usage(self):
        self.parser.set_usage("Usage: %prog [options]")
        self.assertHelpEquals(_expected_help_basic)

    def test_help_long_opts_first(self):
        self.parser.formatter.short_first = 0
        self.assertHelpEquals(_expected_help_long_opts_first)

    def test_help_title_formatter(self):
        with os_helper.EnvironmentVarGuard() as env:
            env["COLUMNS"] = "80"
            self.parser.formatter = TitledHelpFormatter()
            self.assertHelpEquals(_expected_help_title_formatter)

    def test_wrap_columns(self):
        # Ensure that wrapping respects $COLUMNS environment variable.
        # Need to reconstruct the parser, since that's the only time
        # we look at $COLUMNS.
        self.parser = self.make_parser(60)
        self.assertHelpEquals(_expected_help_short_lines)
        self.parser = self.make_parser(0)
        self.assertHelpEquals(_expected_very_help_short_lines)

    def test_help_unicode(self):
        self.parser = InterceptingOptionParser(usage=SUPPRESS_USAGE)
        self.parser.add_option("-a", action="store_true", help="ol\u00E9!")
        expect = """\
Options:
  -h, --help  show this help message and exit
  -a          ol\u00E9!
"""
        self.assertHelpEquals(expect)

    def test_help_unicode_description(self):
        self.parser = InterceptingOptionParser(usage=SUPPRESS_USAGE,
                                               description="ol\u00E9!")
        expect = """\
ol\u00E9!

Options:
  -h, --help  show this help message and exit
"""
        self.assertHelpEquals(expect)

    def test_help_description_groups(self):
        self.parser.set_description(
            "This is the program description for %prog.  %prog has "
            "an option group as well as single options.")

        group = OptionGroup(
            self.parser, "Dangerous Options",
            "Caution: use of these options is at your own risk.  "
            "It is believed that some of them bite.")
        group.add_option("-g", action="store_true", help="Group option.")
        self.parser.add_option_group(group)

        expect = """\
Usage: bar.py [options]

This is the program description for bar.py.  bar.py has an option group as
well as single options.

Options:
  -a APPLE           throw APPLEs at basket
  -b NUM, --boo=NUM  shout "boo!" NUM times (in order to frighten away all the
                     evil spirits that cause trouble and mayhem)
  --foo=FOO          store FOO in the foo list for later fooing
  -h, --help         show this help message and exit

  Dangerous Options:
    Caution: use of these options is at your own risk.  It is believed
    that some of them bite.

    -g               Group option.
"""

        self.assertHelpEquals(expect)

        self.parser.epilog = "Please report bugs to /dev/null."
        self.assertHelpEquals(expect + "\nPlease report bugs to /dev/null.\n")


class TestMatchAbbrev(BaseTest):
    def test_match_abbrev(self):
        self.assertEqual(_match_abbrev("--f",
                                       {"--foz": None,
                                        "--foo": None,
                                        "--fie": None,
                                        "--f": None}),
                         "--f")

    def test_match_abbrev_error(self):
        s = "--f"
        wordmap = {"--foz": None, "--foo": None, "--fie": None}
        self.assertRaises(
            _match_abbrev, (s, wordmap), None,
            BadOptionError, "ambiguous option: --f (--fie, --foo, --foz?)")


class TestParseNumber(BaseTest):
    def setUp(self):
        self.parser = InterceptingOptionParser()
        self.parser.add_option("-n", type=int)
        self.parser.add_option("-l", type=int)

    def test_parse_num_fail(self):
        self.assertRaises(
            _parse_num, ("", int), {},
            ValueError,
            re.compile(r"invalid literal for int().*: '?'?"))
        self.assertRaises(
            _parse_num, ("0xOoops", int), {},
            ValueError,
            re.compile(r"invalid literal for int().*: s?'?0xOoops'?"))

    def test_parse_num_ok(self):
        self.assertEqual(_parse_num("0", int), 0)
        self.assertEqual(_parse_num("0x10", int), 16)
        self.assertEqual(_parse_num("0XA", int), 10)
        self.assertEqual(_parse_num("010", int), 8)
        self.assertEqual(_parse_num("0b11", int), 3)
        self.assertEqual(_parse_num("0b", int), 0)

    def test_numeric_options(self):
        self.assertParseOK(["-n", "42", "-l", "0x20"],
                           { "n": 42, "l": 0x20 }, [])
        self.assertParseOK(["-n", "0b0101", "-l010"],
                           { "n": 5, "l": 8 }, [])
        self.assertParseFail(["-n008"],
                             "option -n: invalid integer value: '008'")
        self.assertParseFail(["-l0b0123"],
                             "option -l: invalid integer value: '0b0123'")
        self.assertParseFail(["-l", "0x12x"],
                             "option -l: invalid integer value: '0x12x'")


class MiscTestCase(unittest.TestCase):
    def test__all__(self):
        not_exported = {'check_builtin', 'AmbiguousOptionError', 'NO_DEFAULT'}
        support.check__all__(self, optparse, not_exported=not_exported)


if __name__ == '__main__':
    unittest.main()
import builtins
import contextlib
import copy
import gc
import pickle
from random import randrange, shuffle
import struct
import sys
import unittest
import weakref
from collections.abc import MutableMapping
from test import mapping_tests, support
from test.support import import_helper


py_coll = import_helper.import_fresh_module('collections',
                                            blocked=['_collections'])
c_coll = import_helper.import_fresh_module('collections',
                                           fresh=['_collections'])


@contextlib.contextmanager
def replaced_module(name, replacement):
    original_module = sys.modules[name]
    sys.modules[name] = replacement
    try:
        yield
    finally:
        sys.modules[name] = original_module


class OrderedDictTests:

    def test_init(self):
        OrderedDict = self.OrderedDict
        with self.assertRaises(TypeError):
            OrderedDict([('a', 1), ('b', 2)], None)                                 # too many args
        pairs = [('a', 1), ('b', 2), ('c', 3), ('d', 4), ('e', 5)]
        self.assertEqual(sorted(OrderedDict(dict(pairs)).items()), pairs)           # dict input
        self.assertEqual(sorted(OrderedDict(**dict(pairs)).items()), pairs)         # kwds input
        self.assertEqual(list(OrderedDict(pairs).items()), pairs)                   # pairs input
        self.assertEqual(list(OrderedDict([('a', 1), ('b', 2), ('c', 9), ('d', 4)],
                                          c=3, e=5).items()), pairs)                # mixed input

        # make sure no positional args conflict with possible kwdargs
        self.assertEqual(list(OrderedDict(self=42).items()), [('self', 42)])
        self.assertEqual(list(OrderedDict(other=42).items()), [('other', 42)])
        self.assertRaises(TypeError, OrderedDict, 42)
        self.assertRaises(TypeError, OrderedDict, (), ())
        self.assertRaises(TypeError, OrderedDict.__init__)

        # Make sure that direct calls to __init__ do not clear previous contents
        d = OrderedDict([('a', 1), ('b', 2), ('c', 3), ('d', 44), ('e', 55)])
        d.__init__([('e', 5), ('f', 6)], g=7, d=4)
        self.assertEqual(list(d.items()),
            [('a', 1), ('b', 2), ('c', 3), ('d', 4), ('e', 5), ('f', 6), ('g', 7)])

    def test_468(self):
        OrderedDict = self.OrderedDict
        items = [('a', 1), ('b', 2), ('c', 3), ('d', 4), ('e', 5), ('f', 6), ('g', 7)]
        shuffle(items)
        argdict = OrderedDict(items)
        d = OrderedDict(**argdict)
        self.assertEqual(list(d.items()), items)

    def test_update(self):
        OrderedDict = self.OrderedDict
        with self.assertRaises(TypeError):
            OrderedDict().update([('a', 1), ('b', 2)], None)                        # too many args
        pairs = [('a', 1), ('b', 2), ('c', 3), ('d', 4), ('e', 5)]
        od = OrderedDict()
        od.update(dict(pairs))
        self.assertEqual(sorted(od.items()), pairs)                                 # dict input
        od = OrderedDict()
        od.update(**dict(pairs))
        self.assertEqual(sorted(od.items()), pairs)                                 # kwds input
        od = OrderedDict()
        od.update(pairs)
        self.assertEqual(list(od.items()), pairs)                                   # pairs input
        od = OrderedDict()
        od.update([('a', 1), ('b', 2), ('c', 9), ('d', 4)], c=3, e=5)
        self.assertEqual(list(od.items()), pairs)                                   # mixed input

        # Issue 9137: Named argument called 'other' or 'self'
        # shouldn't be treated specially.
        od = OrderedDict()
        od.update(self=23)
        self.assertEqual(list(od.items()), [('self', 23)])
        od = OrderedDict()
        od.update(other={})
        self.assertEqual(list(od.items()), [('other', {})])
        od = OrderedDict()
        od.update(red=5, blue=6, other=7, self=8)
        self.assertEqual(sorted(list(od.items())),
                         [('blue', 6), ('other', 7), ('red', 5), ('self', 8)])

        # Make sure that direct calls to update do not clear previous contents
        # add that updates items are not moved to the end
        d = OrderedDict([('a', 1), ('b', 2), ('c', 3), ('d', 44), ('e', 55)])
        d.update([('e', 5), ('f', 6)], g=7, d=4)
        self.assertEqual(list(d.items()),
            [('a', 1), ('b', 2), ('c', 3), ('d', 4), ('e', 5), ('f', 6), ('g', 7)])

        self.assertRaises(TypeError, OrderedDict().update, 42)
        self.assertRaises(TypeError, OrderedDict().update, (), ())
        self.assertRaises(TypeError, OrderedDict.update)

        self.assertRaises(TypeError, OrderedDict().update, 42)
        self.assertRaises(TypeError, OrderedDict().update, (), ())
        self.assertRaises(TypeError, OrderedDict.update)

    def test_init_calls(self):
        calls = []
        class Spam:
            def keys(self):
                calls.append('keys')
                return ()
            def items(self):
                calls.append('items')
                return ()

        self.OrderedDict(Spam())
        self.assertEqual(calls, ['keys'])

    def test_fromkeys(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict.fromkeys('abc')
        self.assertEqual(list(od.items()), [(c, None) for c in 'abc'])
        od = OrderedDict.fromkeys('abc', value=None)
        self.assertEqual(list(od.items()), [(c, None) for c in 'abc'])
        od = OrderedDict.fromkeys('abc', value=0)
        self.assertEqual(list(od.items()), [(c, 0) for c in 'abc'])

    def test_abc(self):
        OrderedDict = self.OrderedDict
        self.assertIsInstance(OrderedDict(), MutableMapping)
        self.assertTrue(issubclass(OrderedDict, MutableMapping))

    def test_clear(self):
        OrderedDict = self.OrderedDict
        pairs = [('c', 1), ('b', 2), ('a', 3), ('d', 4), ('e', 5), ('f', 6)]
        shuffle(pairs)
        od = OrderedDict(pairs)
        self.assertEqual(len(od), len(pairs))
        od.clear()
        self.assertEqual(len(od), 0)

    def test_delitem(self):
        OrderedDict = self.OrderedDict
        pairs = [('c', 1), ('b', 2), ('a', 3), ('d', 4), ('e', 5), ('f', 6)]
        od = OrderedDict(pairs)
        del od['a']
        self.assertNotIn('a', od)
        with self.assertRaises(KeyError):
            del od['a']
        self.assertEqual(list(od.items()), pairs[:2] + pairs[3:])

    def test_setitem(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict([('d', 1), ('b', 2), ('c', 3), ('a', 4), ('e', 5)])
        od['c'] = 10           # existing element
        od['f'] = 20           # new element
        self.assertEqual(list(od.items()),
                         [('d', 1), ('b', 2), ('c', 10), ('a', 4), ('e', 5), ('f', 20)])

    def test_iterators(self):
        OrderedDict = self.OrderedDict
        pairs = [('c', 1), ('b', 2), ('a', 3), ('d', 4), ('e', 5), ('f', 6)]
        shuffle(pairs)
        od = OrderedDict(pairs)
        self.assertEqual(list(od), [t[0] for t in pairs])
        self.assertEqual(list(od.keys()), [t[0] for t in pairs])
        self.assertEqual(list(od.values()), [t[1] for t in pairs])
        self.assertEqual(list(od.items()), pairs)
        self.assertEqual(list(reversed(od)),
                         [t[0] for t in reversed(pairs)])
        self.assertEqual(list(reversed(od.keys())),
                         [t[0] for t in reversed(pairs)])
        self.assertEqual(list(reversed(od.values())),
                         [t[1] for t in reversed(pairs)])
        self.assertEqual(list(reversed(od.items())), list(reversed(pairs)))

    def test_detect_deletion_during_iteration(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict.fromkeys('abc')
        it = iter(od)
        key = next(it)
        del od[key]
        with self.assertRaises(Exception):
            # Note, the exact exception raised is not guaranteed
            # The only guarantee that the next() will not succeed
            next(it)

    def test_sorted_iterators(self):
        OrderedDict = self.OrderedDict
        with self.assertRaises(TypeError):
            OrderedDict([('a', 1), ('b', 2)], None)
        pairs = [('a', 1), ('b', 2), ('c', 3), ('d', 4), ('e', 5)]
        od = OrderedDict(pairs)
        self.assertEqual(sorted(od), [t[0] for t in pairs])
        self.assertEqual(sorted(od.keys()), [t[0] for t in pairs])
        self.assertEqual(sorted(od.values()), [t[1] for t in pairs])
        self.assertEqual(sorted(od.items()), pairs)
        self.assertEqual(sorted(reversed(od)),
                         sorted([t[0] for t in reversed(pairs)]))

    def test_iterators_empty(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict()
        empty = []
        self.assertEqual(list(od), empty)
        self.assertEqual(list(od.keys()), empty)
        self.assertEqual(list(od.values()), empty)
        self.assertEqual(list(od.items()), empty)
        self.assertEqual(list(reversed(od)), empty)
        self.assertEqual(list(reversed(od.keys())), empty)
        self.assertEqual(list(reversed(od.values())), empty)
        self.assertEqual(list(reversed(od.items())), empty)

    def test_popitem(self):
        OrderedDict = self.OrderedDict
        pairs = [('c', 1), ('b', 2), ('a', 3), ('d', 4), ('e', 5), ('f', 6)]
        shuffle(pairs)
        od = OrderedDict(pairs)
        while pairs:
            self.assertEqual(od.popitem(), pairs.pop())
        with self.assertRaises(KeyError):
            od.popitem()
        self.assertEqual(len(od), 0)

    def test_popitem_last(self):
        OrderedDict = self.OrderedDict
        pairs = [(i, i) for i in range(30)]

        obj = OrderedDict(pairs)
        for i in range(8):
            obj.popitem(True)
        obj.popitem(True)
        obj.popitem(last=True)
        self.assertEqual(len(obj), 20)

    def test_pop(self):
        OrderedDict = self.OrderedDict
        pairs = [('c', 1), ('b', 2), ('a', 3), ('d', 4), ('e', 5), ('f', 6)]
        shuffle(pairs)
        od = OrderedDict(pairs)
        shuffle(pairs)
        while pairs:
            k, v = pairs.pop()
            self.assertEqual(od.pop(k), v)
        with self.assertRaises(KeyError):
            od.pop('xyz')
        self.assertEqual(len(od), 0)
        self.assertEqual(od.pop(k, 12345), 12345)

        # make sure pop still works when __missing__ is defined
        class Missing(OrderedDict):
            def __missing__(self, key):
                return 0
        m = Missing(a=1)
        self.assertEqual(m.pop('b', 5), 5)
        self.assertEqual(m.pop('a', 6), 1)
        self.assertEqual(m.pop('a', 6), 6)
        self.assertEqual(m.pop('a', default=6), 6)
        with self.assertRaises(KeyError):
            m.pop('a')

    def test_equality(self):
        OrderedDict = self.OrderedDict
        pairs = [('c', 1), ('b', 2), ('a', 3), ('d', 4), ('e', 5), ('f', 6)]
        shuffle(pairs)
        od1 = OrderedDict(pairs)
        od2 = OrderedDict(pairs)
        self.assertEqual(od1, od2)          # same order implies equality
        pairs = pairs[2:] + pairs[:2]
        od2 = OrderedDict(pairs)
        self.assertNotEqual(od1, od2)       # different order implies inequality
        # comparison to regular dict is not order sensitive
        self.assertEqual(od1, dict(od2))
        self.assertEqual(dict(od2), od1)
        # different length implied inequality
        self.assertNotEqual(od1, OrderedDict(pairs[:-1]))

    def test_copying(self):
        OrderedDict = self.OrderedDict
        # Check that ordered dicts are copyable, deepcopyable, picklable,
        # and have a repr/eval round-trip
        pairs = [('c', 1), ('b', 2), ('a', 3), ('d', 4), ('e', 5), ('f', 6)]
        od = OrderedDict(pairs)
        od.x = ['x']
        od.z = ['z']
        def check(dup):
            msg = "\ncopy: %s\nod: %s" % (dup, od)
            self.assertIsNot(dup, od, msg)
            self.assertEqual(dup, od)
            self.assertEqual(list(dup.items()), list(od.items()))
            self.assertEqual(len(dup), len(od))
            self.assertEqual(type(dup), type(od))
        check(od.copy())
        dup = copy.copy(od)
        check(dup)
        self.assertIs(dup.x, od.x)
        self.assertIs(dup.z, od.z)
        self.assertFalse(hasattr(dup, 'y'))
        dup = copy.deepcopy(od)
        check(dup)
        self.assertEqual(dup.x, od.x)
        self.assertIsNot(dup.x, od.x)
        self.assertEqual(dup.z, od.z)
        self.assertIsNot(dup.z, od.z)
        self.assertFalse(hasattr(dup, 'y'))
        # pickle directly pulls the module, so we have to fake it
        with replaced_module('collections', self.module):
            for proto in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(proto=proto):
                    dup = pickle.loads(pickle.dumps(od, proto))
                    check(dup)
                    self.assertEqual(dup.x, od.x)
                    self.assertEqual(dup.z, od.z)
                    self.assertFalse(hasattr(dup, 'y'))
        check(eval(repr(od)))
        update_test = OrderedDict()
        update_test.update(od)
        check(update_test)
        check(OrderedDict(od))

    def test_yaml_linkage(self):
        OrderedDict = self.OrderedDict
        # Verify that __reduce__ is setup in a way that supports PyYAML's dump() feature.
        # In yaml, lists are native but tuples are not.
        pairs = [('c', 1), ('b', 2), ('a', 3), ('d', 4), ('e', 5), ('f', 6)]
        od = OrderedDict(pairs)
        # yaml.dump(od) -->
        # '!!python/object/apply:__main__.OrderedDict\n- - [a, 1]\n  - [b, 2]\n'
        self.assertTrue(all(type(pair)==list for pair in od.__reduce__()[1]))

    def test_reduce_not_too_fat(self):
        OrderedDict = self.OrderedDict
        # do not save instance dictionary if not needed
        pairs = [('c', 1), ('b', 2), ('a', 3), ('d', 4), ('e', 5), ('f', 6)]
        od = OrderedDict(pairs)
        self.assertIsInstance(od.__dict__, dict)
        self.assertIsNone(od.__reduce__()[2])
        od.x = 10
        self.assertEqual(od.__dict__['x'], 10)
        self.assertEqual(od.__reduce__()[2], {'x': 10})

    def test_pickle_recursive(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict()
        od[1] = od

        # pickle directly pulls the module, so we have to fake it
        with replaced_module('collections', self.module):
            for proto in range(-1, pickle.HIGHEST_PROTOCOL + 1):
                dup = pickle.loads(pickle.dumps(od, proto))
                self.assertIsNot(dup, od)
                self.assertEqual(list(dup.keys()), [1])
                self.assertIs(dup[1], dup)

    def test_repr(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict([('c', 1), ('b', 2), ('a', 3), ('d', 4), ('e', 5), ('f', 6)])
        self.assertEqual(repr(od),
            "OrderedDict({'c': 1, 'b': 2, 'a': 3, 'd': 4, 'e': 5, 'f': 6})")
        self.assertEqual(eval(repr(od)), od)
        self.assertEqual(repr(OrderedDict()), "OrderedDict()")

    def test_repr_recursive(self):
        OrderedDict = self.OrderedDict
        # See issue #9826
        od = OrderedDict.fromkeys('abc')
        od['x'] = od
        self.assertEqual(repr(od),
            "OrderedDict({'a': None, 'b': None, 'c': None, 'x': ...})")

    def test_repr_recursive_values(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict()
        od[42] = od.values()
        r = repr(od)
        # Cannot perform a stronger test, as the contents of the repr
        # are implementation-dependent.  All we can say is that we
        # want a str result, not an exception of any sort.
        self.assertIsInstance(r, str)
        od[42] = od.items()
        r = repr(od)
        # Again.
        self.assertIsInstance(r, str)

    def test_setdefault(self):
        OrderedDict = self.OrderedDict
        pairs = [('c', 1), ('b', 2), ('a', 3), ('d', 4), ('e', 5), ('f', 6)]
        shuffle(pairs)
        od = OrderedDict(pairs)
        pair_order = list(od.items())
        self.assertEqual(od.setdefault('a', 10), 3)
        # make sure order didn't change
        self.assertEqual(list(od.items()), pair_order)
        self.assertEqual(od.setdefault('x', 10), 10)
        # make sure 'x' is added to the end
        self.assertEqual(list(od.items())[-1], ('x', 10))
        self.assertEqual(od.setdefault('g', default=9), 9)

        # make sure setdefault still works when __missing__ is defined
        class Missing(OrderedDict):
            def __missing__(self, key):
                return 0
        self.assertEqual(Missing().setdefault(5, 9), 9)

    def test_reinsert(self):
        OrderedDict = self.OrderedDict
        # Given insert a, insert b, delete a, re-insert a,
        # verify that a is now later than b.
        od = OrderedDict()
        od['a'] = 1
        od['b'] = 2
        del od['a']
        self.assertEqual(list(od.items()), [('b', 2)])
        od['a'] = 1
        self.assertEqual(list(od.items()), [('b', 2), ('a', 1)])

    def test_move_to_end(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict.fromkeys('abcde')
        self.assertEqual(list(od), list('abcde'))
        od.move_to_end('c')
        self.assertEqual(list(od), list('abdec'))
        od.move_to_end('c', False)
        self.assertEqual(list(od), list('cabde'))
        od.move_to_end('c', False)
        self.assertEqual(list(od), list('cabde'))
        od.move_to_end('e')
        self.assertEqual(list(od), list('cabde'))
        od.move_to_end('b', last=False)
        self.assertEqual(list(od), list('bcade'))
        with self.assertRaises(KeyError):
            od.move_to_end('x')
        with self.assertRaises(KeyError):
            od.move_to_end('x', False)

    def test_move_to_end_issue25406(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict.fromkeys('abc')
        od.move_to_end('c', last=False)
        self.assertEqual(list(od), list('cab'))
        od.move_to_end('a', last=False)
        self.assertEqual(list(od), list('acb'))

        od = OrderedDict.fromkeys('abc')
        od.move_to_end('a')
        self.assertEqual(list(od), list('bca'))
        od.move_to_end('c')
        self.assertEqual(list(od), list('bac'))

    def test_sizeof(self):
        OrderedDict = self.OrderedDict
        # Wimpy test: Just verify the reported size is larger than a regular dict
        d = dict(a=1)
        od = OrderedDict(**d)
        self.assertGreater(sys.getsizeof(od), sys.getsizeof(d))

    def test_views(self):
        OrderedDict = self.OrderedDict
        # See http://bugs.python.org/issue24286
        s = 'the quick brown fox jumped over a lazy dog yesterday before dawn'.split()
        od = OrderedDict.fromkeys(s)
        self.assertEqual(od.keys(), dict(od).keys())
        self.assertEqual(od.items(), dict(od).items())

    def test_override_update(self):
        OrderedDict = self.OrderedDict
        # Verify that subclasses can override update() without breaking __init__()
        class MyOD(OrderedDict):
            def update(self, *args, **kwds):
                raise Exception()
        items = [('a', 1), ('c', 3), ('b', 2)]
        self.assertEqual(list(MyOD(items).items()), items)

    def test_highly_nested(self):
        # Issues 25395 and 35983: test that the trashcan mechanism works
        # correctly for OrderedDict: deleting a highly nested OrderDict
        # should not crash Python.
        OrderedDict = self.OrderedDict
        obj = None
        for _ in range(1000):
            obj = OrderedDict([(None, obj)])
        del obj
        support.gc_collect()

    def test_highly_nested_subclass(self):
        # Issues 25395 and 35983: test that the trashcan mechanism works
        # correctly for OrderedDict: deleting a highly nested OrderDict
        # should not crash Python.
        OrderedDict = self.OrderedDict
        deleted = []
        class MyOD(OrderedDict):
            def __del__(self):
                deleted.append(self.i)
        obj = None
        for i in range(100):
            obj = MyOD([(None, obj)])
            obj.i = i
        del obj
        support.gc_collect()
        self.assertEqual(deleted, list(reversed(range(100))))

    def test_delitem_hash_collision(self):
        OrderedDict = self.OrderedDict

        class Key:
            def __init__(self, hash):
                self._hash = hash
                self.value = str(id(self))
            def __hash__(self):
                return self._hash
            def __eq__(self, other):
                try:
                    return self.value == other.value
                except AttributeError:
                    return False
            def __repr__(self):
                return self.value

        def blocking_hash(hash):
            # See the collision-handling in lookdict (in Objects/dictobject.c).
            MINSIZE = 8
            i = (hash & MINSIZE-1)
            return (i << 2) + i + hash + 1

        COLLIDING = 1

        key = Key(COLLIDING)
        colliding = Key(COLLIDING)
        blocking = Key(blocking_hash(COLLIDING))

        od = OrderedDict()
        od[key] = ...
        od[blocking] = ...
        od[colliding] = ...
        od['after'] = ...

        del od[blocking]
        del od[colliding]
        self.assertEqual(list(od.items()), [(key, ...), ('after', ...)])

    def test_issue24347(self):
        OrderedDict = self.OrderedDict

        class Key:
            def __hash__(self):
                return randrange(100000)

        od = OrderedDict()
        for i in range(100):
            key = Key()
            od[key] = i

        # These should not crash.
        with self.assertRaises(KeyError):
            list(od.values())
        with self.assertRaises(KeyError):
            list(od.items())
        with self.assertRaises(KeyError):
            repr(od)
        with self.assertRaises(KeyError):
            od.copy()

    def test_issue24348(self):
        OrderedDict = self.OrderedDict

        class Key:
            def __hash__(self):
                return 1

        od = OrderedDict()
        od[Key()] = 0
        # This should not crash.
        od.popitem()

    def test_issue24667(self):
        """
        dict resizes after a certain number of insertion operations,
        whether or not there were deletions that freed up slots in the
        hash table.  During fast node lookup, OrderedDict must correctly
        respond to all resizes, even if the current "size" is the same
        as the old one.  We verify that here by forcing a dict resize
        on a sparse odict and then perform an operation that should
        trigger an odict resize (e.g. popitem).  One key aspect here is
        that we will keep the size of the odict the same at each popitem
        call.  This verifies that we handled the dict resize properly.
        """
        OrderedDict = self.OrderedDict

        od = OrderedDict()
        for c0 in '0123456789ABCDEF':
            for c1 in '0123456789ABCDEF':
                if len(od) == 4:
                    # This should not raise a KeyError.
                    od.popitem(last=False)
                key = c0 + c1
                od[key] = key

    # Direct use of dict methods

    def test_dict_setitem(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict()
        dict.__setitem__(od, 'spam', 1)
        self.assertNotIn('NULL', repr(od))

    def test_dict_delitem(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict()
        od['spam'] = 1
        od['ham'] = 2
        dict.__delitem__(od, 'spam')
        with self.assertRaises(KeyError):
            repr(od)

    def test_dict_clear(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict()
        od['spam'] = 1
        od['ham'] = 2
        dict.clear(od)
        self.assertNotIn('NULL', repr(od))

    def test_dict_pop(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict()
        od['spam'] = 1
        od['ham'] = 2
        dict.pop(od, 'spam')
        with self.assertRaises(KeyError):
            repr(od)

    def test_dict_popitem(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict()
        od['spam'] = 1
        od['ham'] = 2
        dict.popitem(od)
        with self.assertRaises(KeyError):
            repr(od)

    def test_dict_setdefault(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict()
        dict.setdefault(od, 'spam', 1)
        self.assertNotIn('NULL', repr(od))

    def test_dict_update(self):
        OrderedDict = self.OrderedDict
        od = OrderedDict()
        dict.update(od, [('spam', 1)])
        self.assertNotIn('NULL', repr(od))

    def test_reference_loop(self):
        # Issue 25935
        OrderedDict = self.OrderedDict
        class A:
            od = OrderedDict()
        A.od[A] = None
        r = weakref.ref(A)
        del A
        gc.collect()
        self.assertIsNone(r())

    def test_free_after_iterating(self):
        support.check_free_after_iterating(self, iter, self.OrderedDict)
        support.check_free_after_iterating(self, lambda d: iter(d.keys()), self.OrderedDict)
        support.check_free_after_iterating(self, lambda d: iter(d.values()), self.OrderedDict)
        support.check_free_after_iterating(self, lambda d: iter(d.items()), self.OrderedDict)

    def test_merge_operator(self):
        OrderedDict = self.OrderedDict

        a = OrderedDict({0: 0, 1: 1, 2: 1})
        b = OrderedDict({1: 1, 2: 2, 3: 3})

        c = a.copy()
        d = a.copy()
        c |= b
        d |= list(b.items())
        expected = OrderedDict({0: 0, 1: 1, 2: 2, 3: 3})
        self.assertEqual(a | dict(b), expected)
        self.assertEqual(a | b, expected)
        self.assertEqual(c, expected)
        self.assertEqual(d, expected)

        c = b.copy()
        c |= a
        expected = OrderedDict({1: 1, 2: 1, 3: 3, 0: 0})
        self.assertEqual(dict(b) | a, expected)
        self.assertEqual(b | a, expected)
        self.assertEqual(c, expected)

        self.assertIs(type(a | b), OrderedDict)
        self.assertIs(type(dict(a) | b), OrderedDict)
        self.assertIs(type(a | dict(b)), OrderedDict)

        expected = a.copy()
        a |= ()
        a |= ""
        self.assertEqual(a, expected)

        with self.assertRaises(TypeError):
            a | None
        with self.assertRaises(TypeError):
            a | ()
        with self.assertRaises(TypeError):
            a | "BAD"
        with self.assertRaises(TypeError):
            a | ""
        with self.assertRaises(ValueError):
            a |= "BAD"

    @support.cpython_only
    def test_ordered_dict_items_result_gc(self):
        # bpo-42536: OrderedDict.items's tuple-reuse speed trick breaks the GC's
        # assumptions about what can be untracked. Make sure we re-track result
        # tuples whenever we reuse them.
        it = iter(self.OrderedDict({None: []}).items())
        gc.collect()
        # That GC collection probably untracked the recycled internal result
        # tuple, which is initialized to (None, None). Make sure it's re-tracked
        # when it's mutated and returned from __next__:
        self.assertTrue(gc.is_tracked(next(it)))

class PurePythonOrderedDictTests(OrderedDictTests, unittest.TestCase):

    module = py_coll
    OrderedDict = py_coll.OrderedDict


class CPythonBuiltinDictTests(unittest.TestCase):
    """Builtin dict preserves insertion order.

    Reuse some of tests in OrderedDict selectively.
    """

    module = builtins
    OrderedDict = dict

for method in (
    "test_init test_update test_abc test_clear test_delitem " +
    "test_setitem test_detect_deletion_during_iteration " +
    "test_popitem test_reinsert test_override_update " +
    "test_highly_nested test_highly_nested_subclass " +
    "test_delitem_hash_collision ").split():
    setattr(CPythonBuiltinDictTests, method, getattr(OrderedDictTests, method))
del method


@unittest.skipUnless(c_coll, 'requires the C version of the collections module')
class CPythonOrderedDictTests(OrderedDictTests, unittest.TestCase):

    module = c_coll
    OrderedDict = c_coll.OrderedDict
    check_sizeof = support.check_sizeof

    @support.cpython_only
    def test_sizeof_exact(self):
        OrderedDict = self.OrderedDict
        calcsize = struct.calcsize
        size = support.calcobjsize
        check = self.check_sizeof

        basicsize = size('nQ2P' + '3PnPn2P')
        keysize = calcsize('n2BI2n')

        entrysize = calcsize('n2P')
        p = calcsize('P')
        nodesize = calcsize('Pn2P')

        od = OrderedDict()
        check(od, basicsize)  # 8byte indices + 8*2//3 * entry table
        od.x = 1
        check(od, basicsize)
        od.update([(i, i) for i in range(3)])
        check(od, basicsize + keysize + 8*p + 8 + 5*entrysize + 3*nodesize)
        od.update([(i, i) for i in range(3, 10)])
        check(od, basicsize + keysize + 16*p + 16 + 10*entrysize + 10*nodesize)

        check(od.keys(), size('P'))
        check(od.items(), size('P'))
        check(od.values(), size('P'))

        itersize = size('iP2n2P')
        check(iter(od), itersize)
        check(iter(od.keys()), itersize)
        check(iter(od.items()), itersize)
        check(iter(od.values()), itersize)

    def test_key_change_during_iteration(self):
        OrderedDict = self.OrderedDict

        od = OrderedDict.fromkeys('abcde')
        self.assertEqual(list(od), list('abcde'))
        with self.assertRaises(RuntimeError):
            for i, k in enumerate(od):
                od.move_to_end(k)
                self.assertLess(i, 5)
        with self.assertRaises(RuntimeError):
            for k in od:
                od['f'] = None
        with self.assertRaises(RuntimeError):
            for k in od:
                del od['c']
        self.assertEqual(list(od), list('bdeaf'))

    def test_iterators_pickling(self):
        OrderedDict = self.OrderedDict
        pairs = [('c', 1), ('b', 2), ('a', 3), ('d', 4), ('e', 5), ('f', 6)]
        od = OrderedDict(pairs)

        for method_name in ('keys', 'values', 'items'):
            meth = getattr(od, method_name)
            expected = list(meth())[1:]
            for i in range(pickle.HIGHEST_PROTOCOL + 1):
                with self.subTest(method_name=method_name, protocol=i):
                    it = iter(meth())
                    next(it)
                    p = pickle.dumps(it, i)
                    unpickled = pickle.loads(p)
                    self.assertEqual(list(unpickled), expected)
                    self.assertEqual(list(it), expected)

    @support.cpython_only
    def test_weakref_list_is_not_traversed(self):
        # Check that the weakref list is not traversed when collecting
        # OrderedDict objects. See bpo-39778 for more information.

        gc.collect()

        x = self.OrderedDict()
        x.cycle = x

        cycle = []
        cycle.append(cycle)

        x_ref = weakref.ref(x)
        cycle.append(x_ref)

        del x, cycle, x_ref

        gc.collect()


class PurePythonOrderedDictSubclassTests(PurePythonOrderedDictTests):

    module = py_coll
    class OrderedDict(py_coll.OrderedDict):
        pass


class CPythonOrderedDictSubclassTests(CPythonOrderedDictTests):

    module = c_coll
    class OrderedDict(c_coll.OrderedDict):
        pass


class PurePythonOrderedDictWithSlotsCopyingTests(unittest.TestCase):

    module = py_coll
    class OrderedDict(py_coll.OrderedDict):
        __slots__ = ('x', 'y')
    test_copying = OrderedDictTests.test_copying


@unittest.skipUnless(c_coll, 'requires the C version of the collections module')
class CPythonOrderedDictWithSlotsCopyingTests(unittest.TestCase):

    module = c_coll
    class OrderedDict(c_coll.OrderedDict):
        __slots__ = ('x', 'y')
    test_copying = OrderedDictTests.test_copying


class PurePythonGeneralMappingTests(mapping_tests.BasicTestMappingProtocol):

    @classmethod
    def setUpClass(cls):
        cls.type2test = py_coll.OrderedDict

    def test_popitem(self):
        d = self._empty_mapping()
        self.assertRaises(KeyError, d.popitem)


@unittest.skipUnless(c_coll, 'requires the C version of the collections module')
class CPythonGeneralMappingTests(mapping_tests.BasicTestMappingProtocol):

    @classmethod
    def setUpClass(cls):
        cls.type2test = c_coll.OrderedDict

    def test_popitem(self):
        d = self._empty_mapping()
        self.assertRaises(KeyError, d.popitem)


class PurePythonSubclassMappingTests(mapping_tests.BasicTestMappingProtocol):

    @classmethod
    def setUpClass(cls):
        class MyOrderedDict(py_coll.OrderedDict):
            pass
        cls.type2test = MyOrderedDict

    def test_popitem(self):
        d = self._empty_mapping()
        self.assertRaises(KeyError, d.popitem)


@unittest.skipUnless(c_coll, 'requires the C version of the collections module')
class CPythonSubclassMappingTests(mapping_tests.BasicTestMappingProtocol):

    @classmethod
    def setUpClass(cls):
        class MyOrderedDict(c_coll.OrderedDict):
            pass
        cls.type2test = MyOrderedDict

    def test_popitem(self):
        d = self._empty_mapping()
        self.assertRaises(KeyError, d.popitem)


class SimpleLRUCache:

    def __init__(self, size):
        super().__init__()
        self.size = size
        self.counts = dict.fromkeys(('get', 'set', 'del'), 0)

    def __getitem__(self, item):
        self.counts['get'] += 1
        value = super().__getitem__(item)
        self.move_to_end(item)
        return value

    def __setitem__(self, key, value):
        self.counts['set'] += 1
        while key not in self and len(self) >= self.size:
            self.popitem(last=False)
        super().__setitem__(key, value)
        self.move_to_end(key)

    def __delitem__(self, key):
        self.counts['del'] += 1
        super().__delitem__(key)


class SimpleLRUCacheTests:

    def test_add_after_full(self):
        c = self.type2test(2)
        c['t1'] = 1
        c['t2'] = 2
        c['t3'] = 3
        self.assertEqual(c.counts, {'get': 0, 'set': 3, 'del': 0})
        self.assertEqual(list(c), ['t2', 't3'])
        self.assertEqual(c.counts, {'get': 0, 'set': 3, 'del': 0})

    def test_popitem(self):
        c = self.type2test(3)
        for i in range(1, 4):
            c[i] = i
        self.assertEqual(c.popitem(last=False), (1, 1))
        self.assertEqual(c.popitem(last=True), (3, 3))
        self.assertEqual(c.counts, {'get': 0, 'set': 3, 'del': 0})

    def test_pop(self):
        c = self.type2test(3)
        for i in range(1, 4):
            c[i] = i
        self.assertEqual(c.counts, {'get': 0, 'set': 3, 'del': 0})
        self.assertEqual(c.pop(2), 2)
        self.assertEqual(c.counts, {'get': 0, 'set': 3, 'del': 0})
        self.assertEqual(c.pop(4, 0), 0)
        self.assertEqual(c.counts, {'get': 0, 'set': 3, 'del': 0})
        self.assertRaises(KeyError, c.pop, 4)
        self.assertEqual(c.counts, {'get': 0, 'set': 3, 'del': 0})

    def test_change_order_on_get(self):
        c = self.type2test(3)
        for i in range(1, 4):
            c[i] = i
        self.assertEqual(list(c), list(range(1, 4)))
        self.assertEqual(c.counts, {'get': 0, 'set': 3, 'del': 0})
        self.assertEqual(c[2], 2)
        self.assertEqual(c.counts, {'get': 1, 'set': 3, 'del': 0})
        self.assertEqual(list(c), [1, 3, 2])


class PySimpleLRUCacheTests(SimpleLRUCacheTests, unittest.TestCase):

    class type2test(SimpleLRUCache, py_coll.OrderedDict):
        pass


@unittest.skipUnless(c_coll, 'requires the C version of the collections module')
class CSimpleLRUCacheTests(SimpleLRUCacheTests, unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        class type2test(SimpleLRUCache, c_coll.OrderedDict):
            pass
        cls.type2test = type2test


if __name__ == "__main__":
    unittest.main()
# As a test suite for the os module, this is woefully inadequate, but this
# does add tests for a few functions which have been determined to be more
# portable than they had been thought to be.

import asyncio
import codecs
import contextlib
import decimal
import errno
import fnmatch
import fractions
import itertools
import locale
import os
import pickle
import select
import shutil
import signal
import socket
import stat
import struct
import subprocess
import sys
import sysconfig
import tempfile
import textwrap
import time
import types
import unittest
import uuid
import warnings
from test import support
from test.support import import_helper
from test.support import os_helper
from test.support import socket_helper
from test.support import set_recursion_limit
from test.support import warnings_helper
from platform import win32_is_iot

try:
    import resource
except ImportError:
    resource = None
try:
    import fcntl
except ImportError:
    fcntl = None
try:
    import _winapi
except ImportError:
    _winapi = None
try:
    import pwd
    all_users = [u.pw_uid for u in pwd.getpwall()]
except (ImportError, AttributeError):
    all_users = []
try:
    from _testcapi import INT_MAX, PY_SSIZE_T_MAX
except ImportError:
    INT_MAX = PY_SSIZE_T_MAX = sys.maxsize

try:
    import mmap
except ImportError:
    mmap = None

from test.support.script_helper import assert_python_ok
from test.support import unix_shell
from test.support.os_helper import FakePath


root_in_posix = False
if hasattr(os, 'geteuid'):
    root_in_posix = (os.geteuid() == 0)

# Detect whether we're on a Linux system that uses the (now outdated
# and unmaintained) linuxthreads threading library.  There's an issue
# when combining linuxthreads with a failed execv call: see
# http://bugs.python.org/issue4970.
if hasattr(sys, 'thread_info') and sys.thread_info.version:
    USING_LINUXTHREADS = sys.thread_info.version.startswith("linuxthreads")
else:
    USING_LINUXTHREADS = False

# Issue #14110: Some tests fail on FreeBSD if the user is in the wheel group.
HAVE_WHEEL_GROUP = sys.platform.startswith('freebsd') and os.getgid() == 0


def requires_os_func(name):
    return unittest.skipUnless(hasattr(os, name), 'requires os.%s' % name)


def create_file(filename, content=b'content'):
    with open(filename, "xb", 0) as fp:
        fp.write(content)


# bpo-41625: On AIX, splice() only works with a socket, not with a pipe.
requires_splice_pipe = unittest.skipIf(sys.platform.startswith("aix"),
                                       'on AIX, splice() only accepts sockets')


def tearDownModule():
    asyncio.set_event_loop_policy(None)


class MiscTests(unittest.TestCase):
    def test_getcwd(self):
        cwd = os.getcwd()
        self.assertIsInstance(cwd, str)

    def test_getcwd_long_path(self):
        # bpo-37412: On Linux, PATH_MAX is usually around 4096 bytes. On
        # Windows, MAX_PATH is defined as 260 characters, but Windows supports
        # longer path if longer paths support is enabled. Internally, the os
        # module uses MAXPATHLEN which is at least 1024.
        #
        # Use a directory name of 200 characters to fit into Windows MAX_PATH
        # limit.
        #
        # On Windows, the test can stop when trying to create a path longer
        # than MAX_PATH if long paths support is disabled:
        # see RtlAreLongPathsEnabled().
        min_len = 2000   # characters
        # On VxWorks, PATH_MAX is defined as 1024 bytes. Creating a path
        # longer than PATH_MAX will fail.
        if sys.platform == 'vxworks':
            min_len = 1000
        dirlen = 200     # characters
        dirname = 'python_test_dir_'
        dirname = dirname + ('a' * (dirlen - len(dirname)))

        with tempfile.TemporaryDirectory() as tmpdir:
            with os_helper.change_cwd(tmpdir) as path:
                expected = path

                while True:
                    cwd = os.getcwd()
                    self.assertEqual(cwd, expected)

                    need = min_len - (len(cwd) + len(os.path.sep))
                    if need <= 0:
                        break
                    if len(dirname) > need and need > 0:
                        dirname = dirname[:need]

                    path = os.path.join(path, dirname)
                    try:
                        os.mkdir(path)
                        # On Windows, chdir() can fail
                        # even if mkdir() succeeded
                        os.chdir(path)
                    except FileNotFoundError:
                        # On Windows, catch ERROR_PATH_NOT_FOUND (3) and
                        # ERROR_FILENAME_EXCED_RANGE (206) errors
                        # ("The filename or extension is too long")
                        break
                    except OSError as exc:
                        if exc.errno == errno.ENAMETOOLONG:
                            break
                        else:
                            raise

                    expected = path

                if support.verbose:
                    print(f"Tested current directory length: {len(cwd)}")

    def test_getcwdb(self):
        cwd = os.getcwdb()
        self.assertIsInstance(cwd, bytes)
        self.assertEqual(os.fsdecode(cwd), os.getcwd())


# Tests creating TESTFN
class FileTests(unittest.TestCase):
    def setUp(self):
        if os.path.lexists(os_helper.TESTFN):
            os.unlink(os_helper.TESTFN)
    tearDown = setUp

    def test_access(self):
        f = os.open(os_helper.TESTFN, os.O_CREAT|os.O_RDWR)
        os.close(f)
        self.assertTrue(os.access(os_helper.TESTFN, os.W_OK))

    @unittest.skipIf(
        support.is_emscripten, "Test is unstable under Emscripten."
    )
    @unittest.skipIf(
        support.is_wasi, "WASI does not support dup."
    )
    def test_closerange(self):
        first = os.open(os_helper.TESTFN, os.O_CREAT|os.O_RDWR)
        # We must allocate two consecutive file descriptors, otherwise
        # it will mess up other file descriptors (perhaps even the three
        # standard ones).
        second = os.dup(first)
        try:
            retries = 0
            while second != first + 1:
                os.close(first)
                retries += 1
                if retries > 10:
                    # XXX test skipped
                    self.skipTest("couldn't allocate two consecutive fds")
                first, second = second, os.dup(second)
        finally:
            os.close(second)
        # close a fd that is open, and one that isn't
        os.closerange(first, first + 2)
        self.assertRaises(OSError, os.write, first, b"a")

    @support.cpython_only
    def test_rename(self):
        path = os_helper.TESTFN
        old = sys.getrefcount(path)
        self.assertRaises(TypeError, os.rename, path, 0)
        new = sys.getrefcount(path)
        self.assertEqual(old, new)

    def test_read(self):
        with open(os_helper.TESTFN, "w+b") as fobj:
            fobj.write(b"spam")
            fobj.flush()
            fd = fobj.fileno()
            os.lseek(fd, 0, 0)
            s = os.read(fd, 4)
            self.assertEqual(type(s), bytes)
            self.assertEqual(s, b"spam")

    @support.cpython_only
    # Skip the test on 32-bit platforms: the number of bytes must fit in a
    # Py_ssize_t type
    @unittest.skipUnless(INT_MAX < PY_SSIZE_T_MAX,
                         "needs INT_MAX < PY_SSIZE_T_MAX")
    @support.bigmemtest(size=INT_MAX + 10, memuse=1, dry_run=False)
    def test_large_read(self, size):
        self.addCleanup(os_helper.unlink, os_helper.TESTFN)
        create_file(os_helper.TESTFN, b'test')

        # Issue #21932: Make sure that os.read() does not raise an
        # OverflowError for size larger than INT_MAX
        with open(os_helper.TESTFN, "rb") as fp:
            data = os.read(fp.fileno(), size)

        # The test does not try to read more than 2 GiB at once because the
        # operating system is free to return less bytes than requested.
        self.assertEqual(data, b'test')

    def test_write(self):
        # os.write() accepts bytes- and buffer-like objects but not strings
        fd = os.open(os_helper.TESTFN, os.O_CREAT | os.O_WRONLY)
        self.assertRaises(TypeError, os.write, fd, "beans")
        os.write(fd, b"bacon\n")
        os.write(fd, bytearray(b"eggs\n"))
        os.write(fd, memoryview(b"spam\n"))
        os.close(fd)
        with open(os_helper.TESTFN, "rb") as fobj:
            self.assertEqual(fobj.read().splitlines(),
                [b"bacon", b"eggs", b"spam"])

    def write_windows_console(self, *args):
        retcode = subprocess.call(args,
            # use a new console to not flood the test output
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            # use a shell to hide the console window (SW_HIDE)
            shell=True)
        self.assertEqual(retcode, 0)

    @unittest.skipUnless(sys.platform == 'win32',
                         'test specific to the Windows console')
    def test_write_windows_console(self):
        # Issue #11395: the Windows console returns an error (12: not enough
        # space error) on writing into stdout if stdout mode is binary and the
        # length is greater than 66,000 bytes (or less, depending on heap
        # usage).
        code = "print('x' * 100000)"
        self.write_windows_console(sys.executable, "-c", code)
        self.write_windows_console(sys.executable, "-u", "-c", code)

    def fdopen_helper(self, *args):
        fd = os.open(os_helper.TESTFN, os.O_RDONLY)
        f = os.fdopen(fd, *args, encoding="utf-8")
        f.close()

    def test_fdopen(self):
        fd = os.open(os_helper.TESTFN, os.O_CREAT|os.O_RDWR)
        os.close(fd)

        self.fdopen_helper()
        self.fdopen_helper('r')
        self.fdopen_helper('r', 100)

    def test_replace(self):
        TESTFN2 = os_helper.TESTFN + ".2"
        self.addCleanup(os_helper.unlink, os_helper.TESTFN)
        self.addCleanup(os_helper.unlink, TESTFN2)

        create_file(os_helper.TESTFN, b"1")
        create_file(TESTFN2, b"2")

        os.replace(os_helper.TESTFN, TESTFN2)
        self.assertRaises(FileNotFoundError, os.stat, os_helper.TESTFN)
        with open(TESTFN2, 'r', encoding='utf-8') as f:
            self.assertEqual(f.read(), "1")

    def test_open_keywords(self):
        f = os.open(path=__file__, flags=os.O_RDONLY, mode=0o777,
            dir_fd=None)
        os.close(f)

    def test_symlink_keywords(self):
        symlink = support.get_attribute(os, "symlink")
        try:
            symlink(src='target', dst=os_helper.TESTFN,
                target_is_directory=False, dir_fd=None)
        except (NotImplementedError, OSError):
            pass  # No OS support or unprivileged user

    @unittest.skipUnless(hasattr(os, 'copy_file_range'), 'test needs os.copy_file_range()')
    def test_copy_file_range_invalid_values(self):
        with self.assertRaises(ValueError):
            os.copy_file_range(0, 1, -10)

    @unittest.skipUnless(hasattr(os, 'copy_file_range'), 'test needs os.copy_file_range()')
    def test_copy_file_range(self):
        TESTFN2 = os_helper.TESTFN + ".3"
        data = b'0123456789'

        create_file(os_helper.TESTFN, data)
        self.addCleanup(os_helper.unlink, os_helper.TESTFN)

        in_file = open(os_helper.TESTFN, 'rb')
        self.addCleanup(in_file.close)
        in_fd = in_file.fileno()

        out_file = open(TESTFN2, 'w+b')
        self.addCleanup(os_helper.unlink, TESTFN2)
        self.addCleanup(out_file.close)
        out_fd = out_file.fileno()

        try:
            i = os.copy_file_range(in_fd, out_fd, 5)
        except OSError as e:
            # Handle the case in which Python was compiled
            # in a system with the syscall but without support
            # in the kernel.
            if e.errno != errno.ENOSYS:
                raise
            self.skipTest(e)
        else:
            # The number of copied bytes can be less than
            # the number of bytes originally requested.
            self.assertIn(i, range(0, 6));

            with open(TESTFN2, 'rb') as in_file:
                self.assertEqual(in_file.read(), data[:i])

    @unittest.skipUnless(hasattr(os, 'copy_file_range'), 'test needs os.copy_file_range()')
    def test_copy_file_range_offset(self):
        TESTFN4 = os_helper.TESTFN + ".4"
        data = b'0123456789'
        bytes_to_copy = 6
        in_skip = 3
        out_seek = 5

        create_file(os_helper.TESTFN, data)
        self.addCleanup(os_helper.unlink, os_helper.TESTFN)

        in_file = open(os_helper.TESTFN, 'rb')
        self.addCleanup(in_file.close)
        in_fd = in_file.fileno()

        out_file = open(TESTFN4, 'w+b')
        self.addCleanup(os_helper.unlink, TESTFN4)
        self.addCleanup(out_file.close)
        out_fd = out_file.fileno()

        try:
            i = os.copy_file_range(in_fd, out_fd, bytes_to_copy,
                                   offset_src=in_skip,
                                   offset_dst=out_seek)
        except OSError as e:
            # Handle the case in which Python was compiled
            # in a system with the syscall but without support
            # in the kernel.
            if e.errno != errno.ENOSYS:
                raise
            self.skipTest(e)
        else:
            # The number of copied bytes can be less than
            # the number of bytes originally requested.
            self.assertIn(i, range(0, bytes_to_copy+1));

            with open(TESTFN4, 'rb') as in_file:
                read = in_file.read()
            # seeked bytes (5) are zero'ed
            self.assertEqual(read[:out_seek], b'\x00'*out_seek)
            # 012 are skipped (in_skip)
            # 345678 are copied in the file (in_skip + bytes_to_copy)
            self.assertEqual(read[out_seek:],
                             data[in_skip:in_skip+i])

    @unittest.skipUnless(hasattr(os, 'splice'), 'test needs os.splice()')
    def test_splice_invalid_values(self):
        with self.assertRaises(ValueError):
            os.splice(0, 1, -10)

    @unittest.skipUnless(hasattr(os, 'splice'), 'test needs os.splice()')
    @requires_splice_pipe
    def test_splice(self):
        TESTFN2 = os_helper.TESTFN + ".3"
        data = b'0123456789'

        create_file(os_helper.TESTFN, data)
        self.addCleanup(os_helper.unlink, os_helper.TESTFN)

        in_file = open(os_helper.TESTFN, 'rb')
        self.addCleanup(in_file.close)
        in_fd = in_file.fileno()

        read_fd, write_fd = os.pipe()
        self.addCleanup(lambda: os.close(read_fd))
        self.addCleanup(lambda: os.close(write_fd))

        try:
            i = os.splice(in_fd, write_fd, 5)
        except OSError as e:
            # Handle the case in which Python was compiled
            # in a system with the syscall but without support
            # in the kernel.
            if e.errno != errno.ENOSYS:
                raise
            self.skipTest(e)
        else:
            # The number of copied bytes can be less than
            # the number of bytes originally requested.
            self.assertIn(i, range(0, 6));

            self.assertEqual(os.read(read_fd, 100), data[:i])

    @unittest.skipUnless(hasattr(os, 'splice'), 'test needs os.splice()')
    @requires_splice_pipe
    def test_splice_offset_in(self):
        TESTFN4 = os_helper.TESTFN + ".4"
        data = b'0123456789'
        bytes_to_copy = 6
        in_skip = 3

        create_file(os_helper.TESTFN, data)
        self.addCleanup(os_helper.unlink, os_helper.TESTFN)

        in_file = open(os_helper.TESTFN, 'rb')
        self.addCleanup(in_file.close)
        in_fd = in_file.fileno()

        read_fd, write_fd = os.pipe()
        self.addCleanup(lambda: os.close(read_fd))
        self.addCleanup(lambda: os.close(write_fd))

        try:
            i = os.splice(in_fd, write_fd, bytes_to_copy, offset_src=in_skip)
        except OSError as e:
            # Handle the case in which Python was compiled
            # in a system with the syscall but without support
            # in the kernel.
            if e.errno != errno.ENOSYS:
                raise
            self.skipTest(e)
        else:
            # The number of copied bytes can be less than
            # the number of bytes originally requested.
            self.assertIn(i, range(0, bytes_to_copy+1));

            read = os.read(read_fd, 100)
            # 012 are skipped (in_skip)
            # 345678 are copied in the file (in_skip + bytes_to_copy)
            self.assertEqual(read, data[in_skip:in_skip+i])

    @unittest.skipUnless(hasattr(os, 'splice'), 'test needs os.splice()')
    @requires_splice_pipe
    def test_splice_offset_out(self):
        TESTFN4 = os_helper.TESTFN + ".4"
        data = b'0123456789'
        bytes_to_copy = 6
        out_seek = 3

        create_file(os_helper.TESTFN, data)
        self.addCleanup(os_helper.unlink, os_helper.TESTFN)

        read_fd, write_fd = os.pipe()
        self.addCleanup(lambda: os.close(read_fd))
        self.addCleanup(lambda: os.close(write_fd))
        os.write(write_fd, data)

        out_file = open(TESTFN4, 'w+b')
        self.addCleanup(os_helper.unlink, TESTFN4)
        self.addCleanup(out_file.close)
        out_fd = out_file.fileno()

        try:
            i = os.splice(read_fd, out_fd, bytes_to_copy, offset_dst=out_seek)
        except OSError as e:
            # Handle the case in which Python was compiled
            # in a system with the syscall but without support
            # in the kernel.
            if e.errno != errno.ENOSYS:
                raise
            self.skipTest(e)
        else:
            # The number of copied bytes can be less than
            # the number of bytes originally requested.
            self.assertIn(i, range(0, bytes_to_copy+1));

            with open(TESTFN4, 'rb') as in_file:
                read = in_file.read()
            # seeked bytes (5) are zero'ed
            self.assertEqual(read[:out_seek], b'\x00'*out_seek)
            # 012 are skipped (in_skip)
            # 345678 are copied in the file (in_skip + bytes_to_copy)
            self.assertEqual(read[out_seek:], data[:i])


# Test attributes on return values from os.*stat* family.
class StatAttributeTests(unittest.TestCase):
    def setUp(self):
        self.fname = os_helper.TESTFN
        self.addCleanup(os_helper.unlink, self.fname)
        create_file(self.fname, b"ABC")

    def check_stat_attributes(self, fname):
        result = os.stat(fname)

        # Make sure direct access works
        self.assertEqual(result[stat.ST_SIZE], 3)
        self.assertEqual(result.st_size, 3)

        # Make sure all the attributes are there
        members = dir(result)
        for name in dir(stat):
            if name[:3] == 'ST_':
                attr = name.lower()
                if name.endswith("TIME"):
                    def trunc(x): return int(x)
                else:
                    def trunc(x): return x
                self.assertEqual(trunc(getattr(result, attr)),
                                  result[getattr(stat, name)])
                self.assertIn(attr, members)

        # Make sure that the st_?time and st_?time_ns fields roughly agree
        # (they should always agree up to around tens-of-microseconds)
        for name in 'st_atime st_mtime st_ctime'.split():
            floaty = int(getattr(result, name) * 100000)
            nanosecondy = getattr(result, name + "_ns") // 10000
            self.assertAlmostEqual(floaty, nanosecondy, delta=2)

        try:
            result[200]
            self.fail("No exception raised")
        except IndexError:
            pass

        # Make sure that assignment fails
        try:
            result.st_mode = 1
            self.fail("No exception raised")
        except AttributeError:
            pass

        try:
            result.st_rdev = 1
            self.fail("No exception raised")
        except (AttributeError, TypeError):
            pass

        try:
            result.parrot = 1
            self.fail("No exception raised")
        except AttributeError:
            pass

        # Use the stat_result constructor with a too-short tuple.
        try:
            result2 = os.stat_result((10,))
            self.fail("No exception raised")
        except TypeError:
            pass

        # Use the constructor with a too-long tuple.
        try:
            result2 = os.stat_result((0,1,2,3,4,5,6,7,8,9,10,11,12,13,14))
        except TypeError:
            pass

    def test_stat_attributes(self):
        self.check_stat_attributes(self.fname)

    def test_stat_attributes_bytes(self):
        try:
            fname = self.fname.encode(sys.getfilesystemencoding())
        except UnicodeEncodeError:
            self.skipTest("cannot encode %a for the filesystem" % self.fname)
        self.check_stat_attributes(fname)

    def test_stat_result_pickle(self):
        result = os.stat(self.fname)
        for proto in range(pickle.HIGHEST_PROTOCOL + 1):
            with self.subTest(f'protocol {proto}'):
                p = pickle.dumps(result, proto)
                self.assertIn(b'stat_result', p)
                if proto < 4:
                    self.assertIn(b'cos\nstat_result\n', p)
                unpickled = pickle.loads(p)
                self.assertEqual(result, unpickled)

    @unittest.skipUnless(hasattr(os, 'statvfs'), 'test needs os.statvfs()')
    def test_statvfs_attributes(self):
        result = os.statvfs(self.fname)

        # Make sure direct access works
        self.assertEqual(result.f_bfree, result[3])

        # Make sure all the attributes are there.
        members = ('bsize', 'frsize', 'blocks', 'bfree', 'bavail', 'files',
                    'ffree', 'favail', 'flag', 'namemax')
        for value, member in enumerate(members):
            self.assertEqual(getattr(result, 'f_' + member), result[value])

        self.assertTrue(isinstance(result.f_fsid, int))

        # Test that the size of the tuple doesn't change
        self.assertEqual(len(result), 10)

        # Make sure that assignment really fails
        try:
            result.f_bfree = 1
            self.fail("No exception raised")
        except AttributeError:
            pass

        try:
            result.parrot = 1
            self.fail("No exception raised")
        except AttributeError:
            pass

        # Use the constructor with a too-short tuple.
        try:
            result2 = os.statvfs_result((10,))
            self.fail("No exception raised")
        except TypeError:
            pass

        # Use the constructor with a too-long tuple.
        try:
            result2 = os.statvfs_result((0,1,2,3,4,5,6,7,8,9,10,11,12,13,14))
        except TypeError:
            pass

    @unittest.skipUnless(hasattr(os, 'statvfs'),
                         "need os.statvfs()")
    def test_statvfs_result_pickle(self):
        result = os.statvfs(self.fname)

        for proto in range(pickle.HIGHEST_PROTOCOL + 1):
            p = pickle.dumps(result, proto)
            self.assertIn(b'statvfs_result', p)
            if proto < 4:
                self.assertIn(b'cos\nstatvfs_result\n', p)
            unpickled = pickle.loads(p)
            self.assertEqual(result, unpickled)

    @unittest.skipUnless(sys.platform == "win32", "Win32 specific tests")
    def test_1686475(self):
        # Verify that an open file can be stat'ed
        try:
            os.stat(r"c:\pagefile.sys")
        except FileNotFoundError:
            self.skipTest(r'c:\pagefile.sys does not exist')
        except OSError as e:
            self.fail("Could not stat pagefile.sys")

    @unittest.skipUnless(sys.platform == "win32", "Win32 specific tests")
    @unittest.skipUnless(hasattr(os, "pipe"), "requires os.pipe()")
    def test_15261(self):
        # Verify that stat'ing a closed fd does not cause crash
        r, w = os.pipe()
        try:
            os.stat(r)          # should not raise error
        finally:
            os.close(r)
            os.close(w)
        with self.assertRaises(OSError) as ctx:
            os.stat(r)
        self.assertEqual(ctx.exception.errno, errno.EBADF)

    def check_file_attributes(self, result):
        self.assertTrue(hasattr(result, 'st_file_attributes'))
        self.assertTrue(isinstance(result.st_file_attributes, int))
        self.assertTrue(0 <= result.st_file_attributes <= 0xFFFFFFFF)

    @unittest.skipUnless(sys.platform == "win32",
                         "st_file_attributes is Win32 specific")
    def test_file_attributes(self):
        # test file st_file_attributes (FILE_ATTRIBUTE_DIRECTORY not set)
        result = os.stat(self.fname)
        self.check_file_attributes(result)
        self.assertEqual(
            result.st_file_attributes & stat.FILE_ATTRIBUTE_DIRECTORY,
            0)

        # test directory st_file_attributes (FILE_ATTRIBUTE_DIRECTORY set)
        dirname = os_helper.TESTFN + "dir"
        os.mkdir(dirname)
        self.addCleanup(os.rmdir, dirname)

        result = os.stat(dirname)
        self.check_file_attributes(result)
        self.assertEqual(
            result.st_file_attributes & stat.FILE_ATTRIBUTE_DIRECTORY,
            stat.FILE_ATTRIBUTE_DIRECTORY)

    @unittest.skipUnless(sys.platform == "win32", "Win32 specific tests")
    def test_access_denied(self):
        # Default to FindFirstFile WIN32_FIND_DATA when access is
        # denied. See issue 28075.
        # os.environ['TEMP'] should be located on a volume that
        # supports file ACLs.
        fname = os.path.join(os.environ['TEMP'], self.fname)
        self.addCleanup(os_helper.unlink, fname)
        create_file(fname, b'ABC')
        # Deny the right to [S]YNCHRONIZE on the file to
        # force CreateFile to fail with ERROR_ACCESS_DENIED.
        DETACHED_PROCESS = 8
        subprocess.check_call(
            # bpo-30584: Use security identifier *S-1-5-32-545 instead
            # of localized "Users" to not depend on the locale.
            ['icacls.exe', fname, '/deny', '*S-1-5-32-545:(S)'],
            creationflags=DETACHED_PROCESS
        )
        result = os.stat(fname)
        self.assertNotEqual(result.st_size, 0)
        self.assertTrue(os.path.isfile(fname))

    @unittest.skipUnless(sys.platform == "win32", "Win32 specific tests")
    def test_stat_block_device(self):
        # bpo-38030: os.stat fails for block devices
        # Test a filename like "//./C:"
        fname = "//./" + os.path.splitdrive(os.getcwd())[0]
        result = os.stat(fname)
        self.assertEqual(result.st_mode, stat.S_IFBLK)


class UtimeTests(unittest.TestCase):
    def setUp(self):
        self.dirname = os_helper.TESTFN
        self.fname = os.path.join(self.dirname, "f1")

        self.addCleanup(os_helper.rmtree, self.dirname)
        os.mkdir(self.dirname)
        create_file(self.fname)

    def support_subsecond(self, filename):
        # Heuristic to check if the filesystem supports timestamp with
        # subsecond resolution: check if float and int timestamps are different
        st = os.stat(filename)
        return ((st.st_atime != st[7])
                or (st.st_mtime != st[8])
                or (st.st_ctime != st[9]))

    def _test_utime(self, set_time, filename=None):
        if not filename:
            filename = self.fname

        support_subsecond = self.support_subsecond(filename)
        if support_subsecond:
            # Timestamp with a resolution of 1 microsecond (10^-6).
            #
            # The resolution of the C internal function used by os.utime()
            # depends on the platform: 1 sec, 1 us, 1 ns. Writing a portable
            # test with a resolution of 1 ns requires more work:
            # see the issue #15745.
            atime_ns = 1002003000   # 1.002003 seconds
            mtime_ns = 4005006000   # 4.005006 seconds
        else:
            # use a resolution of 1 second
            atime_ns = 5 * 10**9
            mtime_ns = 8 * 10**9

        set_time(filename, (atime_ns, mtime_ns))
        st = os.stat(filename)

        if support_subsecond:
            self.assertAlmostEqual(st.st_atime, atime_ns * 1e-9, delta=1e-6)
            self.assertAlmostEqual(st.st_mtime, mtime_ns * 1e-9, delta=1e-6)
        else:
            self.assertEqual(st.st_atime, atime_ns * 1e-9)
            self.assertEqual(st.st_mtime, mtime_ns * 1e-9)
        self.assertEqual(st.st_atime_ns, atime_ns)
        self.assertEqual(st.st_mtime_ns, mtime_ns)

    def test_utime(self):
        def set_time(filename, ns):
            # test the ns keyword parameter
            os.utime(filename, ns=ns)
        self._test_utime(set_time)

    @staticmethod
    def ns_to_sec(ns):
        # Convert a number of nanosecond (int) to a number of seconds (float).
        # Round towards infinity by adding 0.5 nanosecond to avoid rounding
        # issue, os.utime() rounds towards minus infinity.
        return (ns * 1e-9) + 0.5e-9

    def test_utime_by_indexed(self):
        # pass times as floating point seconds as the second indexed parameter
        def set_time(filename, ns):
            atime_ns, mtime_ns = ns
            atime = self.ns_to_sec(atime_ns)
            mtime = self.ns_to_sec(mtime_ns)
            # test utimensat(timespec), utimes(timeval), utime(utimbuf)
            # or utime(time_t)
            os.utime(filename, (atime, mtime))
        self._test_utime(set_time)

    def test_utime_by_times(self):
        def set_time(filename, ns):
            atime_ns, mtime_ns = ns
            atime = self.ns_to_sec(atime_ns)
            mtime = self.ns_to_sec(mtime_ns)
            # test the times keyword parameter
            os.utime(filename, times=(atime, mtime))
        self._test_utime(set_time)

    @unittest.skipUnless(os.utime in os.supports_follow_symlinks,
                         "follow_symlinks support for utime required "
                         "for this test.")
    def test_utime_nofollow_symlinks(self):
        def set_time(filename, ns):
            # use follow_symlinks=False to test utimensat(timespec)
            # or lutimes(timeval)
            os.utime(filename, ns=ns, follow_symlinks=False)
        self._test_utime(set_time)

    @unittest.skipUnless(os.utime in os.supports_fd,
                         "fd support for utime required for this test.")
    def test_utime_fd(self):
        def set_time(filename, ns):
            with open(filename, 'wb', 0) as fp:
                # use a file descriptor to test futimens(timespec)
                # or futimes(timeval)
                os.utime(fp.fileno(), ns=ns)
        self._test_utime(set_time)

    @unittest.skipUnless(os.utime in os.supports_dir_fd,
                         "dir_fd support for utime required for this test.")
    def test_utime_dir_fd(self):
        def set_time(filename, ns):
            dirname, name = os.path.split(filename)
            with os_helper.open_dir_fd(dirname) as dirfd:
                # pass dir_fd to test utimensat(timespec) or futimesat(timeval)
                os.utime(name, dir_fd=dirfd, ns=ns)
        self._test_utime(set_time)

    def test_utime_directory(self):
        def set_time(filename, ns):
            # test calling os.utime() on a directory
            os.utime(filename, ns=ns)
        self._test_utime(set_time, filename=self.dirname)

    def _test_utime_current(self, set_time):
        # Get the system clock
        current = time.time()

        # Call os.utime() to set the timestamp to the current system clock
        set_time(self.fname)

        if not self.support_subsecond(self.fname):
            delta = 1.0
        else:
            # On Windows, the usual resolution of time.time() is 15.6 ms.
            # bpo-30649: Tolerate 50 ms for slow Windows buildbots.
            #
            # x86 Gentoo Refleaks 3.x once failed with dt=20.2 ms. So use
            # also 50 ms on other platforms.
            delta = 0.050
        st = os.stat(self.fname)
        msg = ("st_time=%r, current=%r, dt=%r"
               % (st.st_mtime, current, st.st_mtime - current))
        self.assertAlmostEqual(st.st_mtime, current,
                               delta=delta, msg=msg)

    def test_utime_current(self):
        def set_time(filename):
            # Set to the current time in the new way
            os.utime(self.fname)
        self._test_utime_current(set_time)

    def test_utime_current_old(self):
        def set_time(filename):
            # Set to the current time in the old explicit way.
            os.utime(self.fname, None)
        self._test_utime_current(set_time)

    def get_file_system(self, path):
        if sys.platform == 'win32':
            root = os.path.splitdrive(os.path.abspath(path))[0] + '\\'
            import ctypes
            kernel32 = ctypes.windll.kernel32
            buf = ctypes.create_unicode_buffer("", 100)
            ok = kernel32.GetVolumeInformationW(root, None, 0,
                                                None, None, None,
                                                buf, len(buf))
            if ok:
                return buf.value
        # return None if the filesystem is unknown

    def test_large_time(self):
        # Many filesystems are limited to the year 2038. At least, the test
        # pass with NTFS filesystem.
        if self.get_file_system(self.dirname) != "NTFS":
            self.skipTest("requires NTFS")

        large = 5000000000   # some day in 2128
        os.utime(self.fname, (large, large))
        self.assertEqual(os.stat(self.fname).st_mtime, large)

    def test_utime_invalid_arguments(self):
        # seconds and nanoseconds parameters are mutually exclusive
        with self.assertRaises(ValueError):
            os.utime(self.fname, (5, 5), ns=(5, 5))
        with self.assertRaises(TypeError):
            os.utime(self.fname, [5, 5])
        with self.assertRaises(TypeError):
            os.utime(self.fname, (5,))
        with self.assertRaises(TypeError):
            os.utime(self.fname, (5, 5, 5))
        with self.assertRaises(TypeError):
            os.utime(self.fname, ns=[5, 5])
        with self.assertRaises(TypeError):
            os.utime(self.fname, ns=(5,))
        with self.assertRaises(TypeError):
            os.utime(self.fname, ns=(5, 5, 5))

        if os.utime not in os.supports_follow_symlinks:
            with self.assertRaises(NotImplementedError):
                os.utime(self.fname, (5, 5), follow_symlinks=False)
        if os.utime not in os.supports_fd:
            with open(self.fname, 'wb', 0) as fp:
                with self.assertRaises(TypeError):
                    os.utime(fp.fileno(), (5, 5))
        if os.utime not in os.supports_dir_fd:
            with self.assertRaises(NotImplementedError):
                os.utime(self.fname, (5, 5), dir_fd=0)

    @support.cpython_only
    def test_issue31577(self):
        # The interpreter shouldn't crash in case utime() received a bad
        # ns argument.
        def get_bad_int(divmod_ret_val):
            class BadInt:
                def __divmod__(*args):
                    return divmod_ret_val
            return BadInt()
        with self.assertRaises(TypeError):
            os.utime(self.fname, ns=(get_bad_int(42), 1))
        with self.assertRaises(TypeError):
            os.utime(self.fname, ns=(get_bad_int(()), 1))
        with self.assertRaises(TypeError):
            os.utime(self.fname, ns=(get_bad_int((1, 2, 3)), 1))


from test import mapping_tests

class EnvironTests(mapping_tests.BasicTestMappingProtocol):
    """check that os.environ object conform to mapping protocol"""
    type2test = None

    def setUp(self):
        self.__save = dict(os.environ)
        if os.supports_bytes_environ:
            self.__saveb = dict(os.environb)
        for key, value in self._reference().items():
            os.environ[key] = value

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.__save)
        if os.supports_bytes_environ:
            os.environb.clear()
            os.environb.update(self.__saveb)

    def _reference(self):
        return {"KEY1":"VALUE1", "KEY2":"VALUE2", "KEY3":"VALUE3"}

    def _empty_mapping(self):
        os.environ.clear()
        return os.environ

    # Bug 1110478
    @unittest.skipUnless(unix_shell and os.path.exists(unix_shell),
                         'requires a shell')
    @unittest.skipUnless(hasattr(os, 'popen'), "needs os.popen()")
    @support.requires_subprocess()
    def test_update2(self):
        os.environ.clear()
        os.environ.update(HELLO="World")
        with os.popen("%s -c 'echo $HELLO'" % unix_shell) as popen:
            value = popen.read().strip()
            self.assertEqual(value, "World")

    @unittest.skipUnless(unix_shell and os.path.exists(unix_shell),
                         'requires a shell')
    @unittest.skipUnless(hasattr(os, 'popen'), "needs os.popen()")
    @support.requires_subprocess()
    def test_os_popen_iter(self):
        with os.popen("%s -c 'echo \"line1\nline2\nline3\"'"
                      % unix_shell) as popen:
            it = iter(popen)
            self.assertEqual(next(it), "line1\n")
            self.assertEqual(next(it), "line2\n")
            self.assertEqual(next(it), "line3\n")
            self.assertRaises(StopIteration, next, it)

    # Verify environ keys and values from the OS are of the
    # correct str type.
    def test_keyvalue_types(self):
        for key, val in os.environ.items():
            self.assertEqual(type(key), str)
            self.assertEqual(type(val), str)

    def test_items(self):
        for key, value in self._reference().items():
            self.assertEqual(os.environ.get(key), value)

    # Issue 7310
    def test___repr__(self):
        """Check that the repr() of os.environ looks like environ({...})."""
        env = os.environ
        formatted_items = ", ".join(
            f"{key!r}: {value!r}"
            for key, value in env.items()
        )
        self.assertEqual(repr(env), f"environ({{{formatted_items}}})")

    def test_get_exec_path(self):
        defpath_list = os.defpath.split(os.pathsep)
        test_path = ['/monty', '/python', '', '/flying/circus']
        test_env = {'PATH': os.pathsep.join(test_path)}

        saved_environ = os.environ
        try:
            os.environ = dict(test_env)
            # Test that defaulting to os.environ works.
            self.assertSequenceEqual(test_path, os.get_exec_path())
            self.assertSequenceEqual(test_path, os.get_exec_path(env=None))
        finally:
            os.environ = saved_environ

        # No PATH environment variable
        self.assertSequenceEqual(defpath_list, os.get_exec_path({}))
        # Empty PATH environment variable
        self.assertSequenceEqual(('',), os.get_exec_path({'PATH':''}))
        # Supplied PATH environment variable
        self.assertSequenceEqual(test_path, os.get_exec_path(test_env))

        if os.supports_bytes_environ:
            # env cannot contain 'PATH' and b'PATH' keys
            try:
                # ignore BytesWarning warning
                with warnings.catch_warnings(record=True):
                    mixed_env = {'PATH': '1', b'PATH': b'2'}
            except BytesWarning:
                # mixed_env cannot be created with python -bb
                pass
            else:
                self.assertRaises(ValueError, os.get_exec_path, mixed_env)

            # bytes key and/or value
            self.assertSequenceEqual(os.get_exec_path({b'PATH': b'abc'}),
                ['abc'])
            self.assertSequenceEqual(os.get_exec_path({b'PATH': 'abc'}),
                ['abc'])
            self.assertSequenceEqual(os.get_exec_path({'PATH': b'abc'}),
                ['abc'])

    @unittest.skipUnless(os.supports_bytes_environ,
                         "os.environb required for this test.")
    def test_environb(self):
        # os.environ -> os.environb
        value = 'euro\u20ac'
        try:
            value_bytes = value.encode(sys.getfilesystemencoding(),
                                       'surrogateescape')
        except UnicodeEncodeError:
            msg = "U+20AC character is not encodable to %s" % (
                sys.getfilesystemencoding(),)
            self.skipTest(msg)
        os.environ['unicode'] = value
        self.assertEqual(os.environ['unicode'], value)
        self.assertEqual(os.environb[b'unicode'], value_bytes)

        # os.environb -> os.environ
        value = b'\xff'
        os.environb[b'bytes'] = value
        self.assertEqual(os.environb[b'bytes'], value)
        value_str = value.decode(sys.getfilesystemencoding(), 'surrogateescape')
        self.assertEqual(os.environ['bytes'], value_str)

    @support.requires_subprocess()
    def test_putenv_unsetenv(self):
        name = "PYTHONTESTVAR"
        value = "testvalue"
        code = f'import os; print(repr(os.environ.get({name!r})))'

        with os_helper.EnvironmentVarGuard() as env:
            env.pop(name, None)

            os.putenv(name, value)
            proc = subprocess.run([sys.executable, '-c', code], check=True,
                                  stdout=subprocess.PIPE, text=True)
            self.assertEqual(proc.stdout.rstrip(), repr(value))

            os.unsetenv(name)
            proc = subprocess.run([sys.executable, '-c', code], check=True,
                                  stdout=subprocess.PIPE, text=True)
            self.assertEqual(proc.stdout.rstrip(), repr(None))

    # On OS X < 10.6, unsetenv() doesn't return a value (bpo-13415).
    @support.requires_mac_ver(10, 6)
    def test_putenv_unsetenv_error(self):
        # Empty variable name is invalid.
        # "=" and null character are not allowed in a variable name.
        for name in ('', '=name', 'na=me', 'name=', 'name\0', 'na\0me'):
            self.assertRaises((OSError, ValueError), os.putenv, name, "value")
            self.assertRaises((OSError, ValueError), os.unsetenv, name)

        if sys.platform == "win32":
            # On Windows, an environment variable string ("name=value" string)
            # is limited to 32,767 characters
            longstr = 'x' * 32_768
            self.assertRaises(ValueError, os.putenv, longstr, "1")
            self.assertRaises(ValueError, os.putenv, "X", longstr)
            self.assertRaises(ValueError, os.unsetenv, longstr)

    def test_key_type(self):
        missing = 'missingkey'
        self.assertNotIn(missing, os.environ)

        with self.assertRaises(KeyError) as cm:
            os.environ[missing]
        self.assertIs(cm.exception.args[0], missing)
        self.assertTrue(cm.exception.__suppress_context__)

        with self.assertRaises(KeyError) as cm:
            del os.environ[missing]
        self.assertIs(cm.exception.args[0], missing)
        self.assertTrue(cm.exception.__suppress_context__)

    def _test_environ_iteration(self, collection):
        iterator = iter(collection)
        new_key = "__new_key__"

        next(iterator)  # start iteration over os.environ.items

        # add a new key in os.environ mapping
        os.environ[new_key] = "test_environ_iteration"

        try:
            next(iterator)  # force iteration over modified mapping
            self.assertEqual(os.environ[new_key], "test_environ_iteration")
        finally:
            del os.environ[new_key]

    def test_iter_error_when_changing_os_environ(self):
        self._test_environ_iteration(os.environ)

    def test_iter_error_when_changing_os_environ_items(self):
        self._test_environ_iteration(os.environ.items())

    def test_iter_error_when_changing_os_environ_values(self):
        self._test_environ_iteration(os.environ.values())

    def _test_underlying_process_env(self, var, expected):
        if not (unix_shell and os.path.exists(unix_shell)):
            return
        elif not support.has_subprocess_support:
            return

        with os.popen(f"{unix_shell} -c 'echo ${var}'") as popen:
            value = popen.read().strip()

        self.assertEqual(expected, value)

    def test_or_operator(self):
        overridden_key = '_TEST_VAR_'
        original_value = 'original_value'
        os.environ[overridden_key] = original_value

        new_vars_dict = {'_A_': '1', '_B_': '2', overridden_key: '3'}
        expected = dict(os.environ)
        expected.update(new_vars_dict)

        actual = os.environ | new_vars_dict
        self.assertDictEqual(expected, actual)
        self.assertEqual('3', actual[overridden_key])

        new_vars_items = new_vars_dict.items()
        self.assertIs(NotImplemented, os.environ.__or__(new_vars_items))

        self._test_underlying_process_env('_A_', '')
        self._test_underlying_process_env(overridden_key, original_value)

    def test_ior_operator(self):
        overridden_key = '_TEST_VAR_'
        os.environ[overridden_key] = 'original_value'

        new_vars_dict = {'_A_': '1', '_B_': '2', overridden_key: '3'}
        expected = dict(os.environ)
        expected.update(new_vars_dict)

        os.environ |= new_vars_dict
        self.assertEqual(expected, os.environ)
        self.assertEqual('3', os.environ[overridden_key])

        self._test_underlying_process_env('_A_', '1')
        self._test_underlying_process_env(overridden_key, '3')

    def test_ior_operator_invalid_dicts(self):
        os_environ_copy = os.environ.copy()
        with self.assertRaises(TypeError):
            dict_with_bad_key = {1: '_A_'}
            os.environ |= dict_with_bad_key

        with self.assertRaises(TypeError):
            dict_with_bad_val = {'_A_': 1}
            os.environ |= dict_with_bad_val

        # Check nothing was added.
        self.assertEqual(os_environ_copy, os.environ)

    def test_ior_operator_key_value_iterable(self):
        overridden_key = '_TEST_VAR_'
        os.environ[overridden_key] = 'original_value'

        new_vars_items = (('_A_', '1'), ('_B_', '2'), (overridden_key, '3'))
        expected = dict(os.environ)
        expected.update(new_vars_items)

        os.environ |= new_vars_items
        self.assertEqual(expected, os.environ)
        self.assertEqual('3', os.environ[overridden_key])

        self._test_underlying_process_env('_A_', '1')
        self._test_underlying_process_env(overridden_key, '3')

    def test_ror_operator(self):
        overridden_key = '_TEST_VAR_'
        original_value = 'original_value'
        os.environ[overridden_key] = original_value

        new_vars_dict = {'_A_': '1', '_B_': '2', overridden_key: '3'}
        expected = dict(new_vars_dict)
        expected.update(os.environ)

        actual = new_vars_dict | os.environ
        self.assertDictEqual(expected, actual)
        self.assertEqual(original_value, actual[overridden_key])

        new_vars_items = new_vars_dict.items()
        self.assertIs(NotImplemented, os.environ.__ror__(new_vars_items))

        self._test_underlying_process_env('_A_', '')
        self._test_underlying_process_env(overridden_key, original_value)


class WalkTests(unittest.TestCase):
    """Tests for os.walk()."""

    # Wrapper to hide minor differences between os.walk and os.fwalk
    # to tests both functions with the same code base
    def walk(self, top, **kwargs):
        if 'follow_symlinks' in kwargs:
            kwargs['followlinks'] = kwargs.pop('follow_symlinks')
        return os.walk(top, **kwargs)

    def setUp(self):
        join = os.path.join
        self.addCleanup(os_helper.rmtree, os_helper.TESTFN)

        # Build:
        #     TESTFN/
        #       TEST1/              a file kid and two directory kids
        #         tmp1
        #         SUB1/             a file kid and a directory kid
        #           tmp2
        #           SUB11/          no kids
        #         SUB2/             a file kid and a dirsymlink kid
        #           tmp3
        #           SUB21/          not readable
        #             tmp5
        #           link/           a symlink to TESTFN.2
        #           broken_link
        #           broken_link2
        #           broken_link3
        #       TEST2/
        #         tmp4              a lone file
        self.walk_path = join(os_helper.TESTFN, "TEST1")
        self.sub1_path = join(self.walk_path, "SUB1")
        self.sub11_path = join(self.sub1_path, "SUB11")
        sub2_path = join(self.walk_path, "SUB2")
        sub21_path = join(sub2_path, "SUB21")
        tmp1_path = join(self.walk_path, "tmp1")
        tmp2_path = join(self.sub1_path, "tmp2")
        tmp3_path = join(sub2_path, "tmp3")
        tmp5_path = join(sub21_path, "tmp3")
        self.link_path = join(sub2_path, "link")
        t2_path = join(os_helper.TESTFN, "TEST2")
        tmp4_path = join(os_helper.TESTFN, "TEST2", "tmp4")
        broken_link_path = join(sub2_path, "broken_link")
        broken_link2_path = join(sub2_path, "broken_link2")
        broken_link3_path = join(sub2_path, "broken_link3")

        # Create stuff.
        os.makedirs(self.sub11_path)
        os.makedirs(sub2_path)
        os.makedirs(sub21_path)
        os.makedirs(t2_path)

        for path in tmp1_path, tmp2_path, tmp3_path, tmp4_path, tmp5_path:
            with open(path, "x", encoding='utf-8') as f:
                f.write("I'm " + path + " and proud of it.  Blame test_os.\n")

        if os_helper.can_symlink():
            os.symlink(os.path.abspath(t2_path), self.link_path)
            os.symlink('broken', broken_link_path, True)
            os.symlink(join('tmp3', 'broken'), broken_link2_path, True)
            os.symlink(join('SUB21', 'tmp5'), broken_link3_path, True)
            self.sub2_tree = (sub2_path, ["SUB21", "link"],
                              ["broken_link", "broken_link2", "broken_link3",
                               "tmp3"])
        else:
            self.sub2_tree = (sub2_path, ["SUB21"], ["tmp3"])

        if not support.is_emscripten:
            # Emscripten fails with inaccessible directory
            os.chmod(sub21_path, 0)
        try:
            os.listdir(sub21_path)
        except PermissionError:
            self.addCleanup(os.chmod, sub21_path, stat.S_IRWXU)
        else:
            os.chmod(sub21_path, stat.S_IRWXU)
            os.unlink(tmp5_path)
            os.rmdir(sub21_path)
            del self.sub2_tree[1][:1]

    def test_walk_topdown(self):
        # Walk top-down.
        all = list(self.walk(self.walk_path))

        self.assertEqual(len(all), 4)
        # We can't know which order SUB1 and SUB2 will appear in.
        # Not flipped:  TESTFN, SUB1, SUB11, SUB2
        #     flipped:  TESTFN, SUB2, SUB1, SUB11
        flipped = all[0][1][0] != "SUB1"
        all[0][1].sort()
        all[3 - 2 * flipped][-1].sort()
        all[3 - 2 * flipped][1].sort()
        self.assertEqual(all[0], (self.walk_path, ["SUB1", "SUB2"], ["tmp1"]))
        self.assertEqual(all[1 + flipped], (self.sub1_path, ["SUB11"], ["tmp2"]))
        self.assertEqual(all[2 + flipped], (self.sub11_path, [], []))
        self.assertEqual(all[3 - 2 * flipped], self.sub2_tree)

    def test_walk_prune(self, walk_path=None):
        if walk_path is None:
            walk_path = self.walk_path
        # Prune the search.
        all = []
        for root, dirs, files in self.walk(walk_path):
            all.append((root, dirs, files))
            # Don't descend into SUB1.
            if 'SUB1' in dirs:
                # Note that this also mutates the dirs we appended to all!
                dirs.remove('SUB1')

        self.assertEqual(len(all), 2)
        self.assertEqual(all[0], (self.walk_path, ["SUB2"], ["tmp1"]))

        all[1][-1].sort()
        all[1][1].sort()
        self.assertEqual(all[1], self.sub2_tree)

    def test_file_like_path(self):
        self.test_walk_prune(FakePath(self.walk_path))

    def test_walk_bottom_up(self):
        # Walk bottom-up.
        all = list(self.walk(self.walk_path, topdown=False))

        self.assertEqual(len(all), 4, all)
        # We can't know which order SUB1 and SUB2 will appear in.
        # Not flipped:  SUB11, SUB1, SUB2, TESTFN
        #     flipped:  SUB2, SUB11, SUB1, TESTFN
        flipped = all[3][1][0] != "SUB1"
        all[3][1].sort()
        all[2 - 2 * flipped][-1].sort()
        all[2 - 2 * flipped][1].sort()
        self.assertEqual(all[3],
                         (self.walk_path, ["SUB1", "SUB2"], ["tmp1"]))
        self.assertEqual(all[flipped],
                         (self.sub11_path, [], []))
        self.assertEqual(all[flipped + 1],
                         (self.sub1_path, ["SUB11"], ["tmp2"]))
        self.assertEqual(all[2 - 2 * flipped],
                         self.sub2_tree)

    def test_walk_symlink(self):
        if not os_helper.can_symlink():
            self.skipTest("need symlink support")

        # Walk, following symlinks.
        walk_it = self.walk(self.walk_path, follow_symlinks=True)
        for root, dirs, files in walk_it:
            if root == self.link_path:
                self.assertEqual(dirs, [])
                self.assertEqual(files, ["tmp4"])
                break
        else:
            self.fail("Didn't follow symlink with followlinks=True")

    def test_walk_bad_dir(self):
        # Walk top-down.
        errors = []
        walk_it = self.walk(self.walk_path, onerror=errors.append)
        root, dirs, files = next(walk_it)
        self.assertEqual(errors, [])
        dir1 = 'SUB1'
        path1 = os.path.join(root, dir1)
        path1new = os.path.join(root, dir1 + '.new')
        os.rename(path1, path1new)
        try:
            roots = [r for r, d, f in walk_it]
            self.assertTrue(errors)
            self.assertNotIn(path1, roots)
            self.assertNotIn(path1new, roots)
            for dir2 in dirs:
                if dir2 != dir1:
                    self.assertIn(os.path.join(root, dir2), roots)
        finally:
            os.rename(path1new, path1)

    def test_walk_many_open_files(self):
        depth = 30
        base = os.path.join(os_helper.TESTFN, 'deep')
        p = os.path.join(base, *(['d']*depth))
        os.makedirs(p)

        iters = [self.walk(base, topdown=False) for j in range(100)]
        for i in range(depth + 1):
            expected = (p, ['d'] if i else [], [])
            for it in iters:
                self.assertEqual(next(it), expected)
            p = os.path.dirname(p)

        iters = [self.walk(base, topdown=True) for j in range(100)]
        p = base
        for i in range(depth + 1):
            expected = (p, ['d'] if i < depth else [], [])
            for it in iters:
                self.assertEqual(next(it), expected)
            p = os.path.join(p, 'd')

    def test_walk_above_recursion_limit(self):
        depth = 50
        os.makedirs(os.path.join(self.walk_path, *(['d'] * depth)))
        with set_recursion_limit(depth - 5):
            all = list(self.walk(self.walk_path))

        sub2_path = self.sub2_tree[0]
        for root, dirs, files in all:
            if root == sub2_path:
                dirs.sort()
                files.sort()

        d_entries = []
        d_path = self.walk_path
        for _ in range(depth):
            d_path = os.path.join(d_path, "d")
            d_entries.append((d_path, ["d"], []))
        d_entries[-1][1].clear()

        # Sub-sequences where the order is known
        sections = {
            "SUB1": [
                (self.sub1_path, ["SUB11"], ["tmp2"]),
                (self.sub11_path, [], []),
            ],
            "SUB2": [self.sub2_tree],
            "d": d_entries,
        }

        # The ordering of sub-dirs is arbitrary but determines the order in
        # which sub-sequences appear
        dirs = all[0][1]
        expected = [(self.walk_path, dirs, ["tmp1"])]
        for d in dirs:
            expected.extend(sections[d])

        self.assertEqual(len(all), depth + 4)
        self.assertEqual(sorted(dirs), ["SUB1", "SUB2", "d"])
        self.assertEqual(all, expected)


@unittest.skipUnless(hasattr(os, 'fwalk'), "Test needs os.fwalk()")
class FwalkTests(WalkTests):
    """Tests for os.fwalk()."""

    def walk(self, top, **kwargs):
        for root, dirs, files, root_fd in self.fwalk(top, **kwargs):
            yield (root, dirs, files)

    def fwalk(self, *args, **kwargs):
        return os.fwalk(*args, **kwargs)

    def _compare_to_walk(self, walk_kwargs, fwalk_kwargs):
        """
        compare with walk() results.
        """
        walk_kwargs = walk_kwargs.copy()
        fwalk_kwargs = fwalk_kwargs.copy()
        for topdown, follow_symlinks in itertools.product((True, False), repeat=2):
            walk_kwargs.update(topdown=topdown, followlinks=follow_symlinks)
            fwalk_kwargs.update(topdown=topdown, follow_symlinks=follow_symlinks)

            expected = {}
            for root, dirs, files in os.walk(**walk_kwargs):
                expected[root] = (set(dirs), set(files))

            for root, dirs, files, rootfd in self.fwalk(**fwalk_kwargs):
                self.assertIn(root, expected)
                self.assertEqual(expected[root], (set(dirs), set(files)))

    def test_compare_to_walk(self):
        kwargs = {'top': os_helper.TESTFN}
        self._compare_to_walk(kwargs, kwargs)

    def test_dir_fd(self):
        try:
            fd = os.open(".", os.O_RDONLY)
            walk_kwargs = {'top': os_helper.TESTFN}
            fwalk_kwargs = walk_kwargs.copy()
            fwalk_kwargs['dir_fd'] = fd
            self._compare_to_walk(walk_kwargs, fwalk_kwargs)
        finally:
            os.close(fd)

    def test_yields_correct_dir_fd(self):
        # check returned file descriptors
        for topdown, follow_symlinks in itertools.product((True, False), repeat=2):
            args = os_helper.TESTFN, topdown, None
            for root, dirs, files, rootfd in self.fwalk(*args, follow_symlinks=follow_symlinks):
                # check that the FD is valid
                os.fstat(rootfd)
                # redundant check
                os.stat(rootfd)
                # check that listdir() returns consistent information
                self.assertEqual(set(os.listdir(rootfd)), set(dirs) | set(files))

    @unittest.skipIf(
        support.is_emscripten, "Cannot dup stdout on Emscripten"
    )
    def test_fd_leak(self):
        # Since we're opening a lot of FDs, we must be careful to avoid leaks:
        # we both check that calling fwalk() a large number of times doesn't
        # yield EMFILE, and that the minimum allocated FD hasn't changed.
        minfd = os.dup(1)
        os.close(minfd)
        for i in range(256):
            for x in self.fwalk(os_helper.TESTFN):
                pass
        newfd = os.dup(1)
        self.addCleanup(os.close, newfd)
        self.assertEqual(newfd, minfd)

    # fwalk() keeps file descriptors open
    test_walk_many_open_files = None
    # fwalk() still uses recursion
    test_walk_above_recursion_limit = None


class BytesWalkTests(WalkTests):
    """Tests for os.walk() with bytes."""
    def walk(self, top, **kwargs):
        if 'follow_symlinks' in kwargs:
            kwargs['followlinks'] = kwargs.pop('follow_symlinks')
        for broot, bdirs, bfiles in os.walk(os.fsencode(top), **kwargs):
            root = os.fsdecode(broot)
            dirs = list(map(os.fsdecode, bdirs))
            files = list(map(os.fsdecode, bfiles))
            yield (root, dirs, files)
            bdirs[:] = list(map(os.fsencode, dirs))
            bfiles[:] = list(map(os.fsencode, files))

@unittest.skipUnless(hasattr(os, 'fwalk'), "Test needs os.fwalk()")
class BytesFwalkTests(FwalkTests):
    """Tests for os.walk() with bytes."""
    def fwalk(self, top='.', *args, **kwargs):
        for broot, bdirs, bfiles, topfd in os.fwalk(os.fsencode(top), *args, **kwargs):
            root = os.fsdecode(broot)
            dirs = list(map(os.fsdecode, bdirs))
            files = list(map(os.fsdecode, bfiles))
            yield (root, dirs, files, topfd)
            bdirs[:] = list(map(os.fsencode, dirs))
            bfiles[:] = list(map(os.fsencode, files))


class MakedirTests(unittest.TestCase):
    def setUp(self):
        os.mkdir(os_helper.TESTFN)

    def test_makedir(self):
        base = os_helper.TESTFN
        path = os.path.join(base, 'dir1', 'dir2', 'dir3')
        os.makedirs(path)             # Should work
        path = os.path.join(base, 'dir1', 'dir2', 'dir3', 'dir4')
        os.makedirs(path)

        # Try paths with a '.' in them
        self.assertRaises(OSError, os.makedirs, os.curdir)
        path = os.path.join(base, 'dir1', 'dir2', 'dir3', 'dir4', 'dir5', os.curdir)
        os.makedirs(path)
        path = os.path.join(base, 'dir1', os.curdir, 'dir2', 'dir3', 'dir4',
                            'dir5', 'dir6')
        os.makedirs(path)

    @unittest.skipIf(
        support.is_emscripten or support.is_wasi,
        "Emscripten's/WASI's umask is a stub."
    )
    def test_mode(self):
        with os_helper.temp_umask(0o002):
            base = os_helper.TESTFN
            parent = os.path.join(base, 'dir1')
            path = os.path.join(parent, 'dir2')
            os.makedirs(path, 0o555)
            self.assertTrue(os.path.exists(path))
            self.assertTrue(os.path.isdir(path))
            if os.name != 'nt':
                self.assertEqual(os.stat(path).st_mode & 0o777, 0o555)
                self.assertEqual(os.stat(parent).st_mode & 0o777, 0o775)

    @unittest.skipIf(
        support.is_emscripten or support.is_wasi,
        "Emscripten's/WASI's umask is a stub."
    )
    def test_exist_ok_existing_directory(self):
        path = os.path.join(os_helper.TESTFN, 'dir1')
        mode = 0o777
        old_mask = os.umask(0o022)
        os.makedirs(path, mode)
        self.assertRaises(OSError, os.makedirs, path, mode)
        self.assertRaises(OSError, os.makedirs, path, mode, exist_ok=False)
        os.makedirs(path, 0o776, exist_ok=True)
        os.makedirs(path, mode=mode, exist_ok=True)
        os.umask(old_mask)

        # Issue #25583: A drive root could raise PermissionError on Windows
        os.makedirs(os.path.abspath('/'), exist_ok=True)

    @unittest.skipIf(
        support.is_emscripten or support.is_wasi,
        "Emscripten's/WASI's umask is a stub."
    )
    def test_exist_ok_s_isgid_directory(self):
        path = os.path.join(os_helper.TESTFN, 'dir1')
        S_ISGID = stat.S_ISGID
        mode = 0o777
        old_mask = os.umask(0o022)
        try:
            existing_testfn_mode = stat.S_IMODE(
                    os.lstat(os_helper.TESTFN).st_mode)
            try:
                os.chmod(os_helper.TESTFN, existing_testfn_mode | S_ISGID)
            except PermissionError:
                raise unittest.SkipTest('Cannot set S_ISGID for dir.')
            if (os.lstat(os_helper.TESTFN).st_mode & S_ISGID != S_ISGID):
                raise unittest.SkipTest('No support for S_ISGID dir mode.')
            # The os should apply S_ISGID from the parent dir for us, but
            # this test need not depend on that behavior.  Be explicit.
            os.makedirs(path, mode | S_ISGID)
            # http://bugs.python.org/issue14992
            # Should not fail when the bit is already set.
            os.makedirs(path, mode, exist_ok=True)
            # remove the bit.
            os.chmod(path, stat.S_IMODE(os.lstat(path).st_mode) & ~S_ISGID)
            # May work even when the bit is not already set when demanded.
            os.makedirs(path, mode | S_ISGID, exist_ok=True)
        finally:
            os.umask(old_mask)

    def test_exist_ok_existing_regular_file(self):
        base = os_helper.TESTFN
        path = os.path.join(os_helper.TESTFN, 'dir1')
        with open(path, 'w', encoding='utf-8') as f:
            f.write('abc')
        self.assertRaises(OSError, os.makedirs, path)
        self.assertRaises(OSError, os.makedirs, path, exist_ok=False)
        self.assertRaises(OSError, os.makedirs, path, exist_ok=True)
        os.remove(path)

    def tearDown(self):
        path = os.path.join(os_helper.TESTFN, 'dir1', 'dir2', 'dir3',
                            'dir4', 'dir5', 'dir6')
        # If the tests failed, the bottom-most directory ('../dir6')
        # may not have been created, so we look for the outermost directory
        # that exists.
        while not os.path.exists(path) and path != os_helper.TESTFN:
            path = os.path.dirname(path)

        os.removedirs(path)


@os_helper.skip_unless_working_chmod
class ChownFileTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.mkdir(os_helper.TESTFN)

    def test_chown_uid_gid_arguments_must_be_index(self):
        stat = os.stat(os_helper.TESTFN)
        uid = stat.st_uid
        gid = stat.st_gid
        for value in (-1.0, -1j, decimal.Decimal(-1), fractions.Fraction(-2, 2)):
            self.assertRaises(TypeError, os.chown, os_helper.TESTFN, value, gid)
            self.assertRaises(TypeError, os.chown, os_helper.TESTFN, uid, value)
        self.assertIsNone(os.chown(os_helper.TESTFN, uid, gid))
        self.assertIsNone(os.chown(os_helper.TESTFN, -1, -1))

    @unittest.skipUnless(hasattr(os, 'getgroups'), 'need os.getgroups')
    def test_chown_gid(self):
        groups = os.getgroups()
        if len(groups) < 2:
            self.skipTest("test needs at least 2 groups")

        gid_1, gid_2 = groups[:2]
        uid = os.stat(os_helper.TESTFN).st_uid

        os.chown(os_helper.TESTFN, uid, gid_1)
        gid = os.stat(os_helper.TESTFN).st_gid
        self.assertEqual(gid, gid_1)

        os.chown(os_helper.TESTFN, uid, gid_2)
        gid = os.stat(os_helper.TESTFN).st_gid
        self.assertEqual(gid, gid_2)

    @unittest.skipUnless(root_in_posix and len(all_users) > 1,
                         "test needs root privilege and more than one user")
    def test_chown_with_root(self):
        uid_1, uid_2 = all_users[:2]
        gid = os.stat(os_helper.TESTFN).st_gid
        os.chown(os_helper.TESTFN, uid_1, gid)
        uid = os.stat(os_helper.TESTFN).st_uid
        self.assertEqual(uid, uid_1)
        os.chown(os_helper.TESTFN, uid_2, gid)
        uid = os.stat(os_helper.TESTFN).st_uid
        self.assertEqual(uid, uid_2)

    @unittest.skipUnless(not root_in_posix and len(all_users) > 1,
                         "test needs non-root account and more than one user")
    def test_chown_without_permission(self):
        uid_1, uid_2 = all_users[:2]
        gid = os.stat(os_helper.TESTFN).st_gid
        with self.assertRaises(PermissionError):
            os.chown(os_helper.TESTFN, uid_1, gid)
            os.chown(os_helper.TESTFN, uid_2, gid)

    @classmethod
    def tearDownClass(cls):
        os.rmdir(os_helper.TESTFN)


class RemoveDirsTests(unittest.TestCase):
    def setUp(self):
        os.makedirs(os_helper.TESTFN)

    def tearDown(self):
        os_helper.rmtree(os_helper.TESTFN)

    def test_remove_all(self):
        dira = os.path.join(os_helper.TESTFN, 'dira')
        os.mkdir(dira)
        dirb = os.path.join(dira, 'dirb')
        os.mkdir(dirb)
        os.removedirs(dirb)
        self.assertFalse(os.path.exists(dirb))
        self.assertFalse(os.path.exists(dira))
        self.assertFalse(os.path.exists(os_helper.TESTFN))

    def test_remove_partial(self):
        dira = os.path.join(os_helper.TESTFN, 'dira')
        os.mkdir(dira)
        dirb = os.path.join(dira, 'dirb')
        os.mkdir(dirb)
        create_file(os.path.join(dira, 'file.txt'))
        os.removedirs(dirb)
        self.assertFalse(os.path.exists(dirb))
        self.assertTrue(os.path.exists(dira))
        self.assertTrue(os.path.exists(os_helper.TESTFN))

    def test_remove_nothing(self):
        dira = os.path.join(os_helper.TESTFN, 'dira')
        os.mkdir(dira)
        dirb = os.path.join(dira, 'dirb')
        os.mkdir(dirb)
        create_file(os.path.join(dirb, 'file.txt'))
        with self.assertRaises(OSError):
            os.removedirs(dirb)
        self.assertTrue(os.path.exists(dirb))
        self.assertTrue(os.path.exists(dira))
        self.assertTrue(os.path.exists(os_helper.TESTFN))


@unittest.skipIf(support.is_wasi, "WASI has no /dev/null")
class DevNullTests(unittest.TestCase):
    def test_devnull(self):
        with open(os.devnull, 'wb', 0) as f:
            f.write(b'hello')
            f.close()
        with open(os.devnull, 'rb') as f:
            self.assertEqual(f.read(), b'')


class URandomTests(unittest.TestCase):
    def test_urandom_length(self):
        self.assertEqual(len(os.urandom(0)), 0)
        self.assertEqual(len(os.urandom(1)), 1)
        self.assertEqual(len(os.urandom(10)), 10)
        self.assertEqual(len(os.urandom(100)), 100)
        self.assertEqual(len(os.urandom(1000)), 1000)

    def test_urandom_value(self):
        data1 = os.urandom(16)
        self.assertIsInstance(data1, bytes)
        data2 = os.urandom(16)
        self.assertNotEqual(data1, data2)

    def get_urandom_subprocess(self, count):
        code = '\n'.join((
            'import os, sys',
            'data = os.urandom(%s)' % count,
            'sys.stdout.buffer.write(data)',
            'sys.stdout.buffer.flush()'))
        out = assert_python_ok('-c', code)
        stdout = out[1]
        self.assertEqual(len(stdout), count)
        return stdout

    def test_urandom_subprocess(self):
        data1 = self.get_urandom_subprocess(16)
        data2 = self.get_urandom_subprocess(16)
        self.assertNotEqual(data1, data2)


@unittest.skipUnless(hasattr(os, 'getrandom'), 'need os.getrandom()')
class GetRandomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            os.getrandom(1)
        except OSError as exc:
            if exc.errno == errno.ENOSYS:
                # Python compiled on a more recent Linux version
                # than the current Linux kernel
                raise unittest.SkipTest("getrandom() syscall fails with ENOSYS")
            else:
                raise

    def test_getrandom_type(self):
        data = os.getrandom(16)
        self.assertIsInstance(data, bytes)
        self.assertEqual(len(data), 16)

    def test_getrandom0(self):
        empty = os.getrandom(0)
        self.assertEqual(empty, b'')

    def test_getrandom_random(self):
        self.assertTrue(hasattr(os, 'GRND_RANDOM'))

        # Don't test os.getrandom(1, os.GRND_RANDOM) to not consume the rare
        # resource /dev/random

    def test_getrandom_nonblock(self):
        # The call must not fail. Check also that the flag exists
        try:
            os.getrandom(1, os.GRND_NONBLOCK)
        except BlockingIOError:
            # System urandom is not initialized yet
            pass

    def test_getrandom_value(self):
        data1 = os.getrandom(16)
        data2 = os.getrandom(16)
        self.assertNotEqual(data1, data2)


# os.urandom() doesn't use a file descriptor when it is implemented with the
# getentropy() function, the getrandom() function or the getrandom() syscall
OS_URANDOM_DONT_USE_FD = (
    sysconfig.get_config_var('HAVE_GETENTROPY') == 1
    or sysconfig.get_config_var('HAVE_GETRANDOM') == 1
    or sysconfig.get_config_var('HAVE_GETRANDOM_SYSCALL') == 1)

@unittest.skipIf(OS_URANDOM_DONT_USE_FD ,
                 "os.random() does not use a file descriptor")
@unittest.skipIf(sys.platform == "vxworks",
                 "VxWorks can't set RLIMIT_NOFILE to 1")
class URandomFDTests(unittest.TestCase):
    @unittest.skipUnless(resource, "test requires the resource module")
    def test_urandom_failure(self):
        # Check urandom() failing when it is not able to open /dev/random.
        # We spawn a new process to make the test more robust (if getrlimit()
        # failed to restore the file descriptor limit after this, the whole
        # test suite would crash; this actually happened on the OS X Tiger
        # buildbot).
        code = """if 1:
            import errno
            import os
            import resource

            soft_limit, hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
            resource.setrlimit(resource.RLIMIT_NOFILE, (1, hard_limit))
            try:
                os.urandom(16)
            except OSError as e:
                assert e.errno == errno.EMFILE, e.errno
            else:
                raise AssertionError("OSError not raised")
            """
        assert_python_ok('-c', code)

    def test_urandom_fd_closed(self):
        # Issue #21207: urandom() should reopen its fd to /dev/urandom if
        # closed.
        code = """if 1:
            import os
            import sys
            import test.support
            os.urandom(4)
            with test.support.SuppressCrashReport():
                os.closerange(3, 256)
            sys.stdout.buffer.write(os.urandom(4))
            """
        rc, out, err = assert_python_ok('-Sc', code)

    def test_urandom_fd_reopened(self):
        # Issue #21207: urandom() should detect its fd to /dev/urandom
        # changed to something else, and reopen it.
        self.addCleanup(os_helper.unlink, os_helper.TESTFN)
        create_file(os_helper.TESTFN, b"x" * 256)

        code = """if 1:
            import os
            import sys
            import test.support
            os.urandom(4)
            with test.support.SuppressCrashReport():
                for fd in range(3, 256):
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                    else:
                        # Found the urandom fd (XXX hopefully)
                        break
                os.closerange(3, 256)
            with open({TESTFN!r}, 'rb') as f:
                new_fd = f.fileno()
                # Issue #26935: posix allows new_fd and fd to be equal but
                # some libc implementations have dup2 return an error in this
                # case.
                if new_fd != fd:
                    os.dup2(new_fd, fd)
                sys.stdout.buffer.write(os.urandom(4))
                sys.stdout.buffer.write(os.urandom(4))
            """.format(TESTFN=os_helper.TESTFN)
        rc, out, err = assert_python_ok('-Sc', code)
        self.assertEqual(len(out), 8)
        self.assertNotEqual(out[0:4], out[4:8])
        rc, out2, err2 = assert_python_ok('-Sc', code)
        self.assertEqual(len(out2), 8)
        self.assertNotEqual(out2, out)


@contextlib.contextmanager
def _execvpe_mockup(defpath=None):
    """
    Stubs out execv and execve functions when used as context manager.
    Records exec calls. The mock execv and execve functions always raise an
    exception as they would normally never return.
    """
    # A list of tuples containing (function name, first arg, args)
    # of calls to execv or execve that have been made.
    calls = []

    def mock_execv(name, *args):
        calls.append(('execv', name, args))
        raise RuntimeError("execv called")

    def mock_execve(name, *args):
        calls.append(('execve', name, args))
        raise OSError(errno.ENOTDIR, "execve called")

    try:
        orig_execv = os.execv
        orig_execve = os.execve
        orig_defpath = os.defpath
        os.execv = mock_execv
        os.execve = mock_execve
        if defpath is not None:
            os.defpath = defpath
        yield calls
    finally:
        os.execv = orig_execv
        os.execve = orig_execve
        os.defpath = orig_defpath

@unittest.skipUnless(hasattr(os, 'execv'),
                     "need os.execv()")
class ExecTests(unittest.TestCase):
    @unittest.skipIf(USING_LINUXTHREADS,
                     "avoid triggering a linuxthreads bug: see issue #4970")
    def test_execvpe_with_bad_program(self):
        self.assertRaises(OSError, os.execvpe, 'no such app-',
                          ['no such app-'], None)

    def test_execv_with_bad_arglist(self):
        self.assertRaises(ValueError, os.execv, 'notepad', ())
        self.assertRaises(ValueError, os.execv, 'notepad', [])
        self.assertRaises(ValueError, os.execv, 'notepad', ('',))
        self.assertRaises(ValueError, os.execv, 'notepad', [''])

    def test_execvpe_with_bad_arglist(self):
        self.assertRaises(ValueError, os.execvpe, 'notepad', [], None)
        self.assertRaises(ValueError, os.execvpe, 'notepad', [], {})
        self.assertRaises(ValueError, os.execvpe, 'notepad', [''], {})

    @unittest.skipUnless(hasattr(os, '_execvpe'),
                         "No internal os._execvpe function to test.")
    def _test_internal_execvpe(self, test_type):
        program_path = os.sep + 'absolutepath'
        if test_type is bytes:
            program = b'executable'
            fullpath = os.path.join(os.fsencode(program_path), program)
            native_fullpath = fullpath
            arguments = [b'progname', 'arg1', 'arg2']
        else:
            program = 'executable'
            arguments = ['progname', 'arg1', 'arg2']
            fullpath = os.path.join(program_path, program)
            if os.name != "nt":
                native_fullpath = os.fsencode(fullpath)
            else:
                native_fullpath = fullpath
        env = {'spam': 'beans'}

        # test os._execvpe() with an absolute path
        with _execvpe_mockup() as calls:
            self.assertRaises(RuntimeError,
                os._execvpe, fullpath, arguments)
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0], ('execv', fullpath, (arguments,)))

        # test os._execvpe() with a relative path:
        # os.get_exec_path() returns defpath
        with _execvpe_mockup(defpath=program_path) as calls:
            self.assertRaises(OSError,
                os._execvpe, program, arguments, env=env)
            self.assertEqual(len(calls), 1)
            self.assertSequenceEqual(calls[0],
                ('execve', native_fullpath, (arguments, env)))

        # test os._execvpe() with a relative path:
        # os.get_exec_path() reads the 'PATH' variable
        with _execvpe_mockup() as calls:
            env_path = env.copy()
            if test_type is bytes:
                env_path[b'PATH'] = program_path
            else:
                env_path['PATH'] = program_path
            self.assertRaises(OSError,
                os._execvpe, program, arguments, env=env_path)
            self.assertEqual(len(calls), 1)
            self.assertSequenceEqual(calls[0],
                ('execve', native_fullpath, (arguments, env_path)))

    def test_internal_execvpe_str(self):
        self._test_internal_execvpe(str)
        if os.name != "nt":
            self._test_internal_execvpe(bytes)

    def test_execve_invalid_env(self):
        args = [sys.executable, '-c', 'pass']

        # null character in the environment variable name
        newenv = os.environ.copy()
        newenv["FRUIT\0VEGETABLE"] = "cabbage"
        with self.assertRaises(ValueError):
            os.execve(args[0], args, newenv)

        # null character in the environment variable value
        newenv = os.environ.copy()
        newenv["FRUIT"] = "orange\0VEGETABLE=cabbage"
        with self.assertRaises(ValueError):
            os.execve(args[0], args, newenv)

        # equal character in the environment variable name
        newenv = os.environ.copy()
        newenv["FRUIT=ORANGE"] = "lemon"
        with self.assertRaises(ValueError):
            os.execve(args[0], args, newenv)

    @unittest.skipUnless(sys.platform == "win32", "Win32-specific test")
    def test_execve_with_empty_path(self):
        # bpo-32890: Check GetLastError() misuse
        try:
            os.execve('', ['arg'], {})
        except OSError as e:
            self.assertTrue(e.winerror is None or e.winerror != 0)
        else:
            self.fail('No OSError raised')


@unittest.skipUnless(sys.platform == "win32", "Win32 specific tests")
class Win32ErrorTests(unittest.TestCase):
    def setUp(self):
        try:
            os.stat(os_helper.TESTFN)
        except FileNotFoundError:
            exists = False
        except OSError as exc:
            exists = True
            self.fail("file %s must not exist; os.stat failed with %s"
                      % (os_helper.TESTFN, exc))
        else:
            self.fail("file %s must not exist" % os_helper.TESTFN)

    def test_rename(self):
        self.assertRaises(OSError, os.rename, os_helper.TESTFN, os_helper.TESTFN+".bak")

    def test_remove(self):
        self.assertRaises(OSError, os.remove, os_helper.TESTFN)

    def test_chdir(self):
        self.assertRaises(OSError, os.chdir, os_helper.TESTFN)

    def test_mkdir(self):
        self.addCleanup(os_helper.unlink, os_helper.TESTFN)

        with open(os_helper.TESTFN, "x") as f:
            self.assertRaises(OSError, os.mkdir, os_helper.TESTFN)

    def test_utime(self):
        self.assertRaises(OSError, os.utime, os_helper.TESTFN, None)

    def test_chmod(self):
        self.assertRaises(OSError, os.chmod, os_helper.TESTFN, 0)


@unittest.skipIf(support.is_wasi, "Cannot create invalid FD on WASI.")
class TestInvalidFD(unittest.TestCase):
    singles = ["fchdir", "dup", "fdatasync", "fstat",
               "fstatvfs", "fsync", "tcgetpgrp", "ttyname"]
    #singles.append("close")
    #We omit close because it doesn't raise an exception on some platforms
    def get_single(f):
        def helper(self):
            if  hasattr(os, f):
                self.check(getattr(os, f))
        return helper
    for f in singles:
        locals()["test_"+f] = get_single(f)

    def check(self, f, *args, **kwargs):
        try:
            f(os_helper.make_bad_fd(), *args, **kwargs)
        except OSError as e:
            self.assertEqual(e.errno, errno.EBADF)
        else:
            self.fail("%r didn't raise an OSError with a bad file descriptor"
                      % f)

    def test_fdopen(self):
        self.check(os.fdopen, encoding="utf-8")

    @unittest.skipUnless(hasattr(os, 'isatty'), 'test needs os.isatty()')
    def test_isatty(self):
        self.assertEqual(os.isatty(os_helper.make_bad_fd()), False)

    @unittest.skipUnless(hasattr(os, 'closerange'), 'test needs os.closerange()')
    def test_closerange(self):
        fd = os_helper.make_bad_fd()
        # Make sure none of the descriptors we are about to close are
        # currently valid (issue 6542).
        for i in range(10):
            try: os.fstat(fd+i)
            except OSError:
                pass
            else:
                break
        if i < 2:
            raise unittest.SkipTest(
                "Unable to acquire a range of invalid file descriptors")
        self.assertEqual(os.closerange(fd, fd + i-1), None)

    @unittest.skipUnless(hasattr(os, 'dup2'), 'test needs os.dup2()')
    def test_dup2(self):
        self.check(os.dup2, 20)

    @unittest.skipUnless(hasattr(os, 'fchmod'), 'test needs os.fchmod()')
    def test_fchmod(self):
        self.check(os.fchmod, 0)

    @unittest.skipUnless(hasattr(os, 'fchown'), 'test needs os.fchown()')
    def test_fchown(self):
        self.check(os.fchown, -1, -1)

    @unittest.skipUnless(hasattr(os, 'fpathconf'), 'test needs os.fpathconf()')
    @unittest.skipIf(
        support.is_emscripten or support.is_wasi,
        "musl libc issue on Emscripten/WASI, bpo-46390"
    )
    def test_fpathconf(self):
        self.check(os.pathconf, "PC_NAME_MAX")
        self.check(os.fpathconf, "PC_NAME_MAX")

    @unittest.skipUnless(hasattr(os, 'ftruncate'), 'test needs os.ftruncate()')
    def test_ftruncate(self):
        self.check(os.truncate, 0)
        self.check(os.ftruncate, 0)

    @unittest.skipUnless(hasattr(os, 'lseek'), 'test needs os.lseek()')
    def test_lseek(self):
        self.check(os.lseek, 0, 0)

    @unittest.skipUnless(hasattr(os, 'read'), 'test needs os.read()')
    def test_read(self):
        self.check(os.read, 1)

    @unittest.skipUnless(hasattr(os, 'readv'), 'test needs os.readv()')
    def test_readv(self):
        buf = bytearray(10)
        self.check(os.readv, [buf])

    @unittest.skipUnless(hasattr(os, 'tcsetpgrp'), 'test needs os.tcsetpgrp()')
    def test_tcsetpgrpt(self):
        self.check(os.tcsetpgrp, 0)

    @unittest.skipUnless(hasattr(os, 'write'), 'test needs os.write()')
    def test_write(self):
        self.check(os.write, b" ")

    @unittest.skipUnless(hasattr(os, 'writev'), 'test needs os.writev()')
    def test_writev(self):
        self.check(os.writev, [b'abc'])

    @support.requires_subprocess()
    def test_inheritable(self):
        self.check(os.get_inheritable)
        self.check(os.set_inheritable, True)

    @unittest.skipUnless(hasattr(os, 'get_blocking'),
                         'needs os.get_blocking() and os.set_blocking()')
    def test_blocking(self):
        self.check(os.get_blocking)
        self.check(os.set_blocking, True)


@unittest.skipUnless(hasattr(os, 'link'), 'requires os.link')
class LinkTests(unittest.TestCase):
    def setUp(self):
        self.file1 = os_helper.TESTFN
        self.file2 = os.path.join(os_helper.TESTFN + "2")

    def tearDown(self):
        for file in (self.file1, self.file2):
            if os.path.exists(file):
                os.unlink(file)

    def _test_link(self, file1, file2):
        create_file(file1)

        try:
            os.link(file1, file2)
        except PermissionError as e:
            self.skipTest('os.link(): %s' % e)
        with open(file1, "rb") as f1, open(file2, "rb") as f2:
            self.assertTrue(os.path.sameopenfile(f1.fileno(), f2.fileno()))

    def test_link(self):
        self._test_link(self.file1, self.file2)

    def test_link_bytes(self):
        self._test_link(bytes(self.file1, sys.getfilesystemencoding()),
                        bytes(self.file2, sys.getfilesystemencoding()))

    def test_unicode_name(self):
        try:
            os.fsencode("\xf1")
        except UnicodeError:
            raise unittest.SkipTest("Unable to encode for this platform.")

        self.file1 += "\xf1"
        self.file2 = self.file1 + "2"
        self._test_link(self.file1, self.file2)

@unittest.skipIf(sys.platform == "win32", "Posix specific tests")
class PosixUidGidTests(unittest.TestCase):
    # uid_t and gid_t are 32-bit unsigned integers on Linux
    UID_OVERFLOW = (1 << 32)
    GID_OVERFLOW = (1 << 32)

    @unittest.skipUnless(hasattr(os, 'setuid'), 'test needs os.setuid()')
    def test_setuid(self):
        if os.getuid() != 0:
            self.assertRaises(OSError, os.setuid, 0)
        self.assertRaises(TypeError, os.setuid, 'not an int')
        self.assertRaises(OverflowError, os.setuid, self.UID_OVERFLOW)

    @unittest.skipUnless(hasattr(os, 'setgid'), 'test needs os.setgid()')
    def test_setgid(self):
        if os.getuid() != 0 and not HAVE_WHEEL_GROUP:
            self.assertRaises(OSError, os.setgid, 0)
        self.assertRaises(TypeError, os.setgid, 'not an int')
        self.assertRaises(OverflowError, os.setgid, self.GID_OVERFLOW)

    @unittest.skipUnless(hasattr(os, 'seteuid'), 'test needs os.seteuid()')
    def test_seteuid(self):
        if os.getuid() != 0:
            self.assertRaises(OSError, os.seteuid, 0)
        self.assertRaises(TypeError, os.setegid, 'not an int')
        self.assertRaises(OverflowError, os.seteuid, self.UID_OVERFLOW)

    @unittest.skipUnless(hasattr(os, 'setegid'), 'test needs os.setegid()')
    def test_setegid(self):
        if os.getuid() != 0 and not HAVE_WHEEL_GROUP:
            self.assertRaises(OSError, os.setegid, 0)
        self.assertRaises(TypeError, os.setegid, 'not an int')
        self.assertRaises(OverflowError, os.setegid, self.GID_OVERFLOW)

    @unittest.skipUnless(hasattr(os, 'setreuid'), 'test needs os.setreuid()')
    def test_setreuid(self):
        if os.getuid() != 0:
            self.assertRaises(OSError, os.setreuid, 0, 0)
        self.assertRaises(TypeError, os.setreuid, 'not an int', 0)
        self.assertRaises(TypeError, os.setreuid, 0, 'not an int')
        self.assertRaises(OverflowError, os.setreuid, self.UID_OVERFLOW, 0)
        self.assertRaises(OverflowError, os.setreuid, 0, self.UID_OVERFLOW)

    @unittest.skipUnless(hasattr(os, 'setreuid'), 'test needs os.setreuid()')
    @support.requires_subprocess()
    def test_setreuid_neg1(self):
        # Needs to accept -1.  We run this in a subprocess to avoid
        # altering the test runner's process state (issue8045).
        subprocess.check_call([
                sys.executable, '-c',
                'import os,sys;os.setreuid(-1,-1);sys.exit(0)'])

    @unittest.skipUnless(hasattr(os, 'setregid'), 'test needs os.setregid()')
    @support.requires_subprocess()
    def test_setregid(self):
        if os.getuid() != 0 and not HAVE_WHEEL_GROUP:
            self.assertRaises(OSError, os.setregid, 0, 0)
        self.assertRaises(TypeError, os.setregid, 'not an int', 0)
        self.assertRaises(TypeError, os.setregid, 0, 'not an int')
        self.assertRaises(OverflowError, os.setregid, self.GID_OVERFLOW, 0)
        self.assertRaises(OverflowError, os.setregid, 0, self.GID_OVERFLOW)

    @unittest.skipUnless(hasattr(os, 'setregid'), 'test needs os.setregid()')
    @support.requires_subprocess()
    def test_setregid_neg1(self):
        # Needs to accept -1.  We run this in a subprocess to avoid
        # altering the test runner's process state (issue8045).
        subprocess.check_call([
                sys.executable, '-c',
                'import os,sys;os.setregid(-1,-1);sys.exit(0)'])

@unittest.skipIf(sys.platform == "win32", "Posix specific tests")
class Pep383Tests(unittest.TestCase):
    def setUp(self):
        if os_helper.TESTFN_UNENCODABLE:
            self.dir = os_helper.TESTFN_UNENCODABLE
        elif os_helper.TESTFN_NONASCII:
            self.dir = os_helper.TESTFN_NONASCII
        else:
            self.dir = os_helper.TESTFN
        self.bdir = os.fsencode(self.dir)

        bytesfn = []
        def add_filename(fn):
            try:
                fn = os.fsencode(fn)
            except UnicodeEncodeError:
                return
            bytesfn.append(fn)
        add_filename(os_helper.TESTFN_UNICODE)
        if os_helper.TESTFN_UNENCODABLE:
            add_filename(os_helper.TESTFN_UNENCODABLE)
        if os_helper.TESTFN_NONASCII:
            add_filename(os_helper.TESTFN_NONASCII)
        if not bytesfn:
            self.skipTest("couldn't create any non-ascii filename")

        self.unicodefn = set()
        os.mkdir(self.dir)
        try:
            for fn in bytesfn:
                os_helper.create_empty_file(os.path.join(self.bdir, fn))
                fn = os.fsdecode(fn)
                if fn in self.unicodefn:
                    raise ValueError("duplicate filename")
                self.unicodefn.add(fn)
        except:
            shutil.rmtree(self.dir)
            raise

    def tearDown(self):
        shutil.rmtree(self.dir)

    def test_listdir(self):
        expected = self.unicodefn
        found = set(os.listdir(self.dir))
        self.assertEqual(found, expected)
        # test listdir without arguments
        current_directory = os.getcwd()
        try:
            os.chdir(os.sep)
            self.assertEqual(set(os.listdir()), set(os.listdir(os.sep)))
        finally:
            os.chdir(current_directory)

    def test_open(self):
        for fn in self.unicodefn:
            f = open(os.path.join(self.dir, fn), 'rb')
            f.close()

    @unittest.skipUnless(hasattr(os, 'statvfs'),
                            "need os.statvfs()")
    def test_statvfs(self):
        # issue #9645
        for fn in self.unicodefn:
            # should not fail with file not found error
            fullname = os.path.join(self.dir, fn)
            os.statvfs(fullname)

    def test_stat(self):
        for fn in self.unicodefn:
            os.stat(os.path.join(self.dir, fn))

@unittest.skipUnless(sys.platform == "win32", "Win32 specific tests")
class Win32KillTests(unittest.TestCase):
    def _kill(self, sig):
        # Start sys.executable as a subprocess and communicate from the
        # subprocess to the parent that the interpreter is ready. When it
        # becomes ready, send *sig* via os.kill to the subprocess and check
        # that the return code is equal to *sig*.
        import ctypes
        from ctypes import wintypes
        import msvcrt

        # Since we can't access the contents of the process' stdout until the
        # process has exited, use PeekNamedPipe to see what's inside stdout
        # without waiting. This is done so we can tell that the interpreter
        # is started and running at a point where it could handle a signal.
        PeekNamedPipe = ctypes.windll.kernel32.PeekNamedPipe
        PeekNamedPipe.restype = wintypes.BOOL
        PeekNamedPipe.argtypes = (wintypes.HANDLE, # Pipe handle
                                  ctypes.POINTER(ctypes.c_char), # stdout buf
                                  wintypes.DWORD, # Buffer size
                                  ctypes.POINTER(wintypes.DWORD), # bytes read
                                  ctypes.POINTER(wintypes.DWORD), # bytes avail
                                  ctypes.POINTER(wintypes.DWORD)) # bytes left
        msg = "running"
        proc = subprocess.Popen([sys.executable, "-c",
                                 "import sys;"
                                 "sys.stdout.write('{}');"
                                 "sys.stdout.flush();"
                                 "input()".format(msg)],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                stdin=subprocess.PIPE)
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.stderr.close)
        self.addCleanup(proc.stdin.close)

        count, max = 0, 100
        while count < max and proc.poll() is None:
            # Create a string buffer to store the result of stdout from the pipe
            buf = ctypes.create_string_buffer(len(msg))
            # Obtain the text currently in proc.stdout
            # Bytes read/avail/left are left as NULL and unused
            rslt = PeekNamedPipe(msvcrt.get_osfhandle(proc.stdout.fileno()),
                                 buf, ctypes.sizeof(buf), None, None, None)
            self.assertNotEqual(rslt, 0, "PeekNamedPipe failed")
            if buf.value:
                self.assertEqual(msg, buf.value.decode())
                break
            time.sleep(0.1)
            count += 1
        else:
            self.fail("Did not receive communication from the subprocess")

        os.kill(proc.pid, sig)
        self.assertEqual(proc.wait(), sig)

    def test_kill_sigterm(self):
        # SIGTERM doesn't mean anything special, but make sure it works
        self._kill(signal.SIGTERM)

    def test_kill_int(self):
        # os.kill on Windows can take an int which gets set as the exit code
        self._kill(100)

    @unittest.skipIf(mmap is None, "requires mmap")
    def _kill_with_event(self, event, name):
        tagname = "test_os_%s" % uuid.uuid1()
        m = mmap.mmap(-1, 1, tagname)
        m[0] = 0
        # Run a script which has console control handling enabled.
        proc = subprocess.Popen([sys.executable,
                   os.path.join(os.path.dirname(__file__),
                                "win_console_handler.py"), tagname],
                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        # Let the interpreter startup before we send signals. See #3137.
        count, max = 0, 100
        while count < max and proc.poll() is None:
            if m[0] == 1:
                break
            time.sleep(0.1)
            count += 1
        else:
            # Forcefully kill the process if we weren't able to signal it.
            os.kill(proc.pid, signal.SIGINT)
            self.fail("Subprocess didn't finish initialization")
        os.kill(proc.pid, event)
        # proc.send_signal(event) could also be done here.
        # Allow time for the signal to be passed and the process to exit.
        time.sleep(0.5)
        if not proc.poll():
            # Forcefully kill the process if we weren't able to signal it.
            os.kill(proc.pid, signal.SIGINT)
            self.fail("subprocess did not stop on {}".format(name))

    @unittest.skip("subprocesses aren't inheriting Ctrl+C property")
    @support.requires_subprocess()
    def test_CTRL_C_EVENT(self):
        from ctypes import wintypes
        import ctypes

        # Make a NULL value by creating a pointer with no argument.
        NULL = ctypes.POINTER(ctypes.c_int)()
        SetConsoleCtrlHandler = ctypes.windll.kernel32.SetConsoleCtrlHandler
        SetConsoleCtrlHandler.argtypes = (ctypes.POINTER(ctypes.c_int),
                                          wintypes.BOOL)
        SetConsoleCtrlHandler.restype = wintypes.BOOL

        # Calling this with NULL and FALSE causes the calling process to
        # handle Ctrl+C, rather than ignore it. This property is inherited
        # by subprocesses.
        SetConsoleCtrlHandler(NULL, 0)

        self._kill_with_event(signal.CTRL_C_EVENT, "CTRL_C_EVENT")

    @support.requires_subprocess()
    def test_CTRL_BREAK_EVENT(self):
        self._kill_with_event(signal.CTRL_BREAK_EVENT, "CTRL_BREAK_EVENT")


@unittest.skipUnless(sys.platform == "win32", "Win32 specific tests")
class Win32ListdirTests(unittest.TestCase):
    """Test listdir on Windows."""

    def setUp(self):
        self.created_paths = []
        for i in range(2):
            dir_name = 'SUB%d' % i
            dir_path = os.path.join(os_helper.TESTFN, dir_name)
            file_name = 'FILE%d' % i
            file_path = os.path.join(os_helper.TESTFN, file_name)
            os.makedirs(dir_path)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("I'm %s and proud of it. Blame test_os.\n" % file_path)
            self.created_paths.extend([dir_name, file_name])
        self.created_paths.sort()

    def tearDown(self):
        shutil.rmtree(os_helper.TESTFN)

    def test_listdir_no_extended_path(self):
        """Test when the path is not an "extended" path."""
        # unicode
        self.assertEqual(
                sorted(os.listdir(os_helper.TESTFN)),
                self.created_paths)

        # bytes
        self.assertEqual(
                sorted(os.listdir(os.fsencode(os_helper.TESTFN))),
                [os.fsencode(path) for path in self.created_paths])

    def test_listdir_extended_path(self):
        """Test when the path starts with '\\\\?\\'."""
        # See: http://msdn.microsoft.com/en-us/library/windows/desktop/aa365247(v=vs.85).aspx#maxpath
        # unicode
        path = '\\\\?\\' + os.path.abspath(os_helper.TESTFN)
        self.assertEqual(
                sorted(os.listdir(path)),
                self.created_paths)

        # bytes
        path = b'\\\\?\\' + os.fsencode(os.path.abspath(os_helper.TESTFN))
        self.assertEqual(
                sorted(os.listdir(path)),
                [os.fsencode(path) for path in self.created_paths])


@unittest.skipUnless(hasattr(os, 'readlink'), 'needs os.readlink()')
class ReadlinkTests(unittest.TestCase):
    filelink = 'readlinktest'
    filelink_target = os.path.abspath(__file__)
    filelinkb = os.fsencode(filelink)
    filelinkb_target = os.fsencode(filelink_target)

    def assertPathEqual(self, left, right):
        left = os.path.normcase(left)
        right = os.path.normcase(right)
        if sys.platform == 'win32':
            # Bad practice to blindly strip the prefix as it may be required to
            # correctly refer to the file, but we're only comparing paths here.
            has_prefix = lambda p: p.startswith(
                b'\\\\?\\' if isinstance(p, bytes) else '\\\\?\\')
            if has_prefix(left):
                left = left[4:]
            if has_prefix(right):
                right = right[4:]
        self.assertEqual(left, right)

    def setUp(self):
        self.assertTrue(os.path.exists(self.filelink_target))
        self.assertTrue(os.path.exists(self.filelinkb_target))
        self.assertFalse(os.path.exists(self.filelink))
        self.assertFalse(os.path.exists(self.filelinkb))

    def test_not_symlink(self):
        filelink_target = FakePath(self.filelink_target)
        self.assertRaises(OSError, os.readlink, self.filelink_target)
        self.assertRaises(OSError, os.readlink, filelink_target)

    def test_missing_link(self):
        self.assertRaises(FileNotFoundError, os.readlink, 'missing-link')
        self.assertRaises(FileNotFoundError, os.readlink,
                          FakePath('missing-link'))

    @os_helper.skip_unless_symlink
    def test_pathlike(self):
        os.symlink(self.filelink_target, self.filelink)
        self.addCleanup(os_helper.unlink, self.filelink)
        filelink = FakePath(self.filelink)
        self.assertPathEqual(os.readlink(filelink), self.filelink_target)

    @os_helper.skip_unless_symlink
    def test_pathlike_bytes(self):
        os.symlink(self.filelinkb_target, self.filelinkb)
        self.addCleanup(os_helper.unlink, self.filelinkb)
        path = os.readlink(FakePath(self.filelinkb))
        self.assertPathEqual(path, self.filelinkb_target)
        self.assertIsInstance(path, bytes)

    @os_helper.skip_unless_symlink
    def test_bytes(self):
        os.symlink(self.filelinkb_target, self.filelinkb)
        self.addCleanup(os_helper.unlink, self.filelinkb)
        path = os.readlink(self.filelinkb)
        self.assertPathEqual(path, self.filelinkb_target)
        self.assertIsInstance(path, bytes)


@unittest.skipUnless(sys.platform == "win32", "Win32 specific tests")
@os_helper.skip_unless_symlink
class Win32SymlinkTests(unittest.TestCase):
    filelink = 'filelinktest'
    filelink_target = os.path.abspath(__file__)
    dirlink = 'dirlinktest'
    dirlink_target = os.path.dirname(filelink_target)
    missing_link = 'missing link'

    def setUp(self):
        assert os.path.exists(self.dirlink_target)
        assert os.path.exists(self.filelink_target)
        assert not os.path.exists(self.dirlink)
        assert not os.path.exists(self.filelink)
        assert not os.path.exists(self.missing_link)

    def tearDown(self):
        if os.path.exists(self.filelink):
            os.remove(self.filelink)
        if os.path.exists(self.dirlink):
            os.rmdir(self.dirlink)
        if os.path.lexists(self.missing_link):
            os.remove(self.missing_link)

    def test_directory_link(self):
        os.symlink(self.dirlink_target, self.dirlink)
        self.assertTrue(os.path.exists(self.dirlink))
        self.assertTrue(os.path.isdir(self.dirlink))
        self.assertTrue(os.path.islink(self.dirlink))
        self.check_stat(self.dirlink, self.dirlink_target)

    def test_file_link(self):
        os.symlink(self.filelink_target, self.filelink)
        self.assertTrue(os.path.exists(self.filelink))
        self.assertTrue(os.path.isfile(self.filelink))
        self.assertTrue(os.path.islink(self.filelink))
        self.check_stat(self.filelink, self.filelink_target)

    def _create_missing_dir_link(self):
        'Create a "directory" link to a non-existent target'
        linkname = self.missing_link
        if os.path.lexists(linkname):
            os.remove(linkname)
        target = r'c:\\target does not exist.29r3c740'
        assert not os.path.exists(target)
        target_is_dir = True
        os.symlink(target, linkname, target_is_dir)

    def test_remove_directory_link_to_missing_target(self):
        self._create_missing_dir_link()
        # For compatibility with Unix, os.remove will check the
        #  directory status and call RemoveDirectory if the symlink
        #  was created with target_is_dir==True.
        os.remove(self.missing_link)

    def test_isdir_on_directory_link_to_missing_target(self):
        self._create_missing_dir_link()
        self.assertFalse(os.path.isdir(self.missing_link))

    def test_rmdir_on_directory_link_to_missing_target(self):
        self._create_missing_dir_link()
        os.rmdir(self.missing_link)

    def check_stat(self, link, target):
        self.assertEqual(os.stat(link), os.stat(target))
        self.assertNotEqual(os.lstat(link), os.stat(link))

        bytes_link = os.fsencode(link)
        self.assertEqual(os.stat(bytes_link), os.stat(target))
        self.assertNotEqual(os.lstat(bytes_link), os.stat(bytes_link))

    def test_12084(self):
        level1 = os.path.abspath(os_helper.TESTFN)
        level2 = os.path.join(level1, "level2")
        level3 = os.path.join(level2, "level3")
        self.addCleanup(os_helper.rmtree, level1)

        os.mkdir(level1)
        os.mkdir(level2)
        os.mkdir(level3)

        file1 = os.path.abspath(os.path.join(level1, "file1"))
        create_file(file1)

        orig_dir = os.getcwd()
        try:
            os.chdir(level2)
            link = os.path.join(level2, "link")
            os.symlink(os.path.relpath(file1), "link")
            self.assertIn("link", os.listdir(os.getcwd()))

            # Check os.stat calls from the same dir as the link
            self.assertEqual(os.stat(file1), os.stat("link"))

            # Check os.stat calls from a dir below the link
            os.chdir(level1)
            self.assertEqual(os.stat(file1),
                             os.stat(os.path.relpath(link)))

            # Check os.stat calls from a dir above the link
            os.chdir(level3)
            self.assertEqual(os.stat(file1),
                             os.stat(os.path.relpath(link)))
        finally:
            os.chdir(orig_dir)

    @unittest.skipUnless(os.path.lexists(r'C:\Users\All Users')
                            and os.path.exists(r'C:\ProgramData'),
                            'Test directories not found')
    def test_29248(self):
        # os.symlink() calls CreateSymbolicLink, which creates
        # the reparse data buffer with the print name stored
        # first, so the offset is always 0. CreateSymbolicLink
        # stores the "PrintName" DOS path (e.g. "C:\") first,
        # with an offset of 0, followed by the "SubstituteName"
        # NT path (e.g. "\??\C:\"). The "All Users" link, on
        # the other hand, seems to have been created manually
        # with an inverted order.
        target = os.readlink(r'C:\Users\All Users')
        self.assertTrue(os.path.samefile(target, r'C:\ProgramData'))

    def test_buffer_overflow(self):
        # Older versions would have a buffer overflow when detecting
        # whether a link source was a directory. This test ensures we
        # no longer crash, but does not otherwise validate the behavior
        segment = 'X' * 27
        path = os.path.join(*[segment] * 10)
        test_cases = [
            # overflow with absolute src
            ('\\' + path, segment),
            # overflow dest with relative src
            (segment, path),
            # overflow when joining src
            (path[:180], path[:180]),
        ]
        for src, dest in test_cases:
            try:
                os.symlink(src, dest)
            except FileNotFoundError:
                pass
            else:
                try:
                    os.remove(dest)
                except OSError:
                    pass
            # Also test with bytes, since that is a separate code path.
            try:
                os.symlink(os.fsencode(src), os.fsencode(dest))
            except FileNotFoundError:
                pass
            else:
                try:
                    os.remove(dest)
                except OSError:
                    pass

    def test_appexeclink(self):
        root = os.path.expandvars(r'%LOCALAPPDATA%\Microsoft\WindowsApps')
        if not os.path.isdir(root):
            self.skipTest("test requires a WindowsApps directory")

        aliases = [os.path.join(root, a)
                   for a in fnmatch.filter(os.listdir(root), '*.exe')]

        for alias in aliases:
            if support.verbose:
                print()
                print("Testing with", alias)
            st = os.lstat(alias)
            self.assertEqual(st, os.stat(alias))
            self.assertFalse(stat.S_ISLNK(st.st_mode))
            self.assertEqual(st.st_reparse_tag, stat.IO_REPARSE_TAG_APPEXECLINK)
            self.assertTrue(os.path.isfile(alias))
            # testing the first one we see is sufficient
            break
        else:
            self.skipTest("test requires an app execution alias")

@unittest.skipUnless(sys.platform == "win32", "Win32 specific tests")
class Win32JunctionTests(unittest.TestCase):
    junction = 'junctiontest'
    junction_target = os.path.dirname(os.path.abspath(__file__))

    def setUp(self):
        assert os.path.exists(self.junction_target)
        assert not os.path.lexists(self.junction)

    def tearDown(self):
        if os.path.lexists(self.junction):
            os.unlink(self.junction)

    def test_create_junction(self):
        _winapi.CreateJunction(self.junction_target, self.junction)
        self.assertTrue(os.path.lexists(self.junction))
        self.assertTrue(os.path.exists(self.junction))
        self.assertTrue(os.path.isdir(self.junction))
        self.assertNotEqual(os.stat(self.junction), os.lstat(self.junction))
        self.assertEqual(os.stat(self.junction), os.stat(self.junction_target))

        # bpo-37834: Junctions are not recognized as links.
        self.assertFalse(os.path.islink(self.junction))
        self.assertEqual(os.path.normcase("\\\\?\\" + self.junction_target),
                         os.path.normcase(os.readlink(self.junction)))

    def test_unlink_removes_junction(self):
        _winapi.CreateJunction(self.junction_target, self.junction)
        self.assertTrue(os.path.exists(self.junction))
        self.assertTrue(os.path.lexists(self.junction))

        os.unlink(self.junction)
        self.assertFalse(os.path.exists(self.junction))

@unittest.skipUnless(sys.platform == "win32", "Win32 specific tests")
class Win32NtTests(unittest.TestCase):
    def test_getfinalpathname_handles(self):
        nt = import_helper.import_module('nt')
        ctypes = import_helper.import_module('ctypes')
        import ctypes.wintypes

        kernel = ctypes.WinDLL('Kernel32.dll', use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.wintypes.HANDLE

        kernel.GetProcessHandleCount.restype = ctypes.wintypes.BOOL
        kernel.GetProcessHandleCount.argtypes = (ctypes.wintypes.HANDLE,
                                                 ctypes.wintypes.LPDWORD)

        # This is a pseudo-handle that doesn't need to be closed
        hproc = kernel.GetCurrentProcess()

        handle_count = ctypes.wintypes.DWORD()
        ok = kernel.GetProcessHandleCount(hproc, ctypes.byref(handle_count))
        self.assertEqual(1, ok)

        before_count = handle_count.value

        # The first two test the error path, __file__ tests the success path
        filenames = [
            r'\\?\C:',
            r'\\?\NUL',
            r'\\?\CONIN',
            __file__,
        ]

        for _ in range(10):
            for name in filenames:
                try:
                    nt._getfinalpathname(name)
                except Exception:
                    # Failure is expected
                    pass
                try:
                    os.stat(name)
                except Exception:
                    pass

        ok = kernel.GetProcessHandleCount(hproc, ctypes.byref(handle_count))
        self.assertEqual(1, ok)

        handle_delta = handle_count.value - before_count

        self.assertEqual(0, handle_delta)

    @support.requires_subprocess()
    def test_stat_unlink_race(self):
        # bpo-46785: the implementation of os.stat() falls back to reading
        # the parent directory if CreateFileW() fails with a permission
        # error. If reading the parent directory fails because the file or
        # directory are subsequently unlinked, or because the volume or
        # share are no longer available, then the original permission error
        # should not be restored.
        filename =  os_helper.TESTFN
        self.addCleanup(os_helper.unlink, filename)
        deadline = time.time() + 5
        command = textwrap.dedent("""\
            import os
            import sys
            import time

            filename = sys.argv[1]
            deadline = float(sys.argv[2])

            while time.time() < deadline:
                try:
                    with open(filename, "w") as f:
                        pass
                except OSError:
                    pass
                try:
                    os.remove(filename)
                except OSError:
                    pass
            """)

        with subprocess.Popen([sys.executable, '-c', command, filename, str(deadline)]) as proc:
            while time.time() < deadline:
                try:
                    os.stat(filename)
                except FileNotFoundError as e:
                    assert e.winerror == 2  # ERROR_FILE_NOT_FOUND
            try:
                proc.wait(1)
            except subprocess.TimeoutExpired:
                proc.terminate()


@os_helper.skip_unless_symlink
class NonLocalSymlinkTests(unittest.TestCase):

    def setUp(self):
        r"""
        Create this structure:

        base
         \___ some_dir
        """
        os.makedirs('base/some_dir')

    def tearDown(self):
        shutil.rmtree('base')

    def test_directory_link_nonlocal(self):
        """
        The symlink target should resolve relative to the link, not relative
        to the current directory.

        Then, link base/some_link -> base/some_dir and ensure that some_link
        is resolved as a directory.

        In issue13772, it was discovered that directory detection failed if
        the symlink target was not specified relative to the current
        directory, which was a defect in the implementation.
        """
        src = os.path.join('base', 'some_link')
        os.symlink('some_dir', src)
        assert os.path.isdir(src)


class FSEncodingTests(unittest.TestCase):
    def test_nop(self):
        self.assertEqual(os.fsencode(b'abc\xff'), b'abc\xff')
        self.assertEqual(os.fsdecode('abc\u0141'), 'abc\u0141')

    def test_identity(self):
        # assert fsdecode(fsencode(x)) == x
        for fn in ('unicode\u0141', 'latin\xe9', 'ascii'):
            try:
                bytesfn = os.fsencode(fn)
            except UnicodeEncodeError:
                continue
            self.assertEqual(os.fsdecode(bytesfn), fn)



class DeviceEncodingTests(unittest.TestCase):

    def test_bad_fd(self):
        # Return None when an fd doesn't actually exist.
        self.assertIsNone(os.device_encoding(123456))

    @unittest.skipUnless(os.isatty(0) and not win32_is_iot() and (sys.platform.startswith('win') or
            (hasattr(locale, 'nl_langinfo') and hasattr(locale, 'CODESET'))),
            'test requires a tty and either Windows or nl_langinfo(CODESET)')
    @unittest.skipIf(
        support.is_emscripten, "Cannot get encoding of stdin on Emscripten"
    )
    def test_device_encoding(self):
        encoding = os.device_encoding(0)
        self.assertIsNotNone(encoding)
        self.assertTrue(codecs.lookup(encoding))


@support.requires_subprocess()
class PidTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(os, 'getppid'), "test needs os.getppid")
    def test_getppid(self):
        p = subprocess.Popen([sys.executable, '-c',
                              'import os; print(os.getppid())'],
                             stdout=subprocess.PIPE)
        stdout, _ = p.communicate()
        # We are the parent of our subprocess
        self.assertEqual(int(stdout), os.getpid())

    def check_waitpid(self, code, exitcode, callback=None):
        if sys.platform == 'win32':
            # On Windows, os.spawnv() simply joins arguments with spaces:
            # arguments need to be quoted
            args = [f'"{sys.executable}"', '-c', f'"{code}"']
        else:
            args = [sys.executable, '-c', code]
        pid = os.spawnv(os.P_NOWAIT, sys.executable, args)

        if callback is not None:
            callback(pid)

        # don't use support.wait_process() to test directly os.waitpid()
        # and os.waitstatus_to_exitcode()
        pid2, status = os.waitpid(pid, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), exitcode)
        self.assertEqual(pid2, pid)

    def test_waitpid(self):
        self.check_waitpid(code='pass', exitcode=0)

    def test_waitstatus_to_exitcode(self):
        exitcode = 23
        code = f'import sys; sys.exit({exitcode})'
        self.check_waitpid(code, exitcode=exitcode)

        with self.assertRaises(TypeError):
            os.waitstatus_to_exitcode(0.0)

    @unittest.skipUnless(sys.platform == 'win32', 'win32-specific test')
    def test_waitpid_windows(self):
        # bpo-40138: test os.waitpid() and os.waitstatus_to_exitcode()
        # with exit code larger than INT_MAX.
        STATUS_CONTROL_C_EXIT = 0xC000013A
        code = f'import _winapi; _winapi.ExitProcess({STATUS_CONTROL_C_EXIT})'
        self.check_waitpid(code, exitcode=STATUS_CONTROL_C_EXIT)

    @unittest.skipUnless(sys.platform == 'win32', 'win32-specific test')
    def test_waitstatus_to_exitcode_windows(self):
        max_exitcode = 2 ** 32 - 1
        for exitcode in (0, 1, 5, max_exitcode):
            self.assertEqual(os.waitstatus_to_exitcode(exitcode << 8),
                             exitcode)

        # invalid values
        with self.assertRaises(ValueError):
            os.waitstatus_to_exitcode((max_exitcode + 1) << 8)
        with self.assertRaises(OverflowError):
            os.waitstatus_to_exitcode(-1)

    # Skip the test on Windows
    @unittest.skipUnless(hasattr(signal, 'SIGKILL'), 'need signal.SIGKILL')
    def test_waitstatus_to_exitcode_kill(self):
        code = f'import time; time.sleep({support.LONG_TIMEOUT})'
        signum = signal.SIGKILL

        def kill_process(pid):
            os.kill(pid, signum)

        self.check_waitpid(code, exitcode=-signum, callback=kill_process)


@support.requires_subprocess()
class SpawnTests(unittest.TestCase):
    def create_args(self, *, with_env=False, use_bytes=False):
        self.exitcode = 17

        filename = os_helper.TESTFN
        self.addCleanup(os_helper.unlink, filename)

        if not with_env:
            code = 'import sys; sys.exit(%s)' % self.exitcode
        else:
            self.env = dict(os.environ)
            # create an unique key
            self.key = str(uuid.uuid4())
            self.env[self.key] = self.key
            # read the variable from os.environ to check that it exists
            code = ('import sys, os; magic = os.environ[%r]; sys.exit(%s)'
                    % (self.key, self.exitcode))

        with open(filename, "w", encoding="utf-8") as fp:
            fp.write(code)

        args = [sys.executable, filename]
        if use_bytes:
            args = [os.fsencode(a) for a in args]
            self.env = {os.fsencode(k): os.fsencode(v)
                        for k, v in self.env.items()}

        return args

    @requires_os_func('spawnl')
    def test_spawnl(self):
        args = self.create_args()
        exitcode = os.spawnl(os.P_WAIT, args[0], *args)
        self.assertEqual(exitcode, self.exitcode)

    @requires_os_func('spawnle')
    def test_spawnle(self):
        args = self.create_args(with_env=True)
        exitcode = os.spawnle(os.P_WAIT, args[0], *args, self.env)
        self.assertEqual(exitcode, self.exitcode)

    @requires_os_func('spawnlp')
    def test_spawnlp(self):
        args = self.create_args()
        exitcode = os.spawnlp(os.P_WAIT, args[0], *args)
        self.assertEqual(exitcode, self.exitcode)

    @requires_os_func('spawnlpe')
    def test_spawnlpe(self):
        args = self.create_args(with_env=True)
        exitcode = os.spawnlpe(os.P_WAIT, args[0], *args, self.env)
        self.assertEqual(exitcode, self.exitcode)

    @requires_os_func('spawnv')
    def test_spawnv(self):
        args = self.create_args()
        exitcode = os.spawnv(os.P_WAIT, args[0], args)
        self.assertEqual(exitcode, self.exitcode)

        # Test for PyUnicode_FSConverter()
        exitcode = os.spawnv(os.P_WAIT, FakePath(args[0]), args)
        self.assertEqual(exitcode, self.exitcode)

    @requires_os_func('spawnve')
    def test_spawnve(self):
        args = self.create_args(with_env=True)
        exitcode = os.spawnve(os.P_WAIT, args[0], args, self.env)
        self.assertEqual(exitcode, self.exitcode)

    @requires_os_func('spawnvp')
    def test_spawnvp(self):
        args = self.create_args()
        exitcode = os.spawnvp(os.P_WAIT, args[0], args)
        self.assertEqual(exitcode, self.exitcode)

    @requires_os_func('spawnvpe')
    def test_spawnvpe(self):
        args = self.create_args(with_env=True)
        exitcode = os.spawnvpe(os.P_WAIT, args[0], args, self.env)
        self.assertEqual(exitcode, self.exitcode)

    @requires_os_func('spawnv')
    def test_nowait(self):
        args = self.create_args()
        pid = os.spawnv(os.P_NOWAIT, args[0], args)
        support.wait_process(pid, exitcode=self.exitcode)

    @requires_os_func('spawnve')
    def test_spawnve_bytes(self):
        # Test bytes handling in parse_arglist and parse_envlist (#28114)
        args = self.create_args(with_env=True, use_bytes=True)
        exitcode = os.spawnve(os.P_WAIT, args[0], args, self.env)
        self.assertEqual(exitcode, self.exitcode)

    @requires_os_func('spawnl')
    def test_spawnl_noargs(self):
        args = self.create_args()
        self.assertRaises(ValueError, os.spawnl, os.P_NOWAIT, args[0])
        self.assertRaises(ValueError, os.spawnl, os.P_NOWAIT, args[0], '')

    @requires_os_func('spawnle')
    def test_spawnle_noargs(self):
        args = self.create_args()
        self.assertRaises(ValueError, os.spawnle, os.P_NOWAIT, args[0], {})
        self.assertRaises(ValueError, os.spawnle, os.P_NOWAIT, args[0], '', {})

    @requires_os_func('spawnv')
    def test_spawnv_noargs(self):
        args = self.create_args()
        self.assertRaises(ValueError, os.spawnv, os.P_NOWAIT, args[0], ())
        self.assertRaises(ValueError, os.spawnv, os.P_NOWAIT, args[0], [])
        self.assertRaises(ValueError, os.spawnv, os.P_NOWAIT, args[0], ('',))
        self.assertRaises(ValueError, os.spawnv, os.P_NOWAIT, args[0], [''])

    @requires_os_func('spawnve')
    def test_spawnve_noargs(self):
        args = self.create_args()
        self.assertRaises(ValueError, os.spawnve, os.P_NOWAIT, args[0], (), {})
        self.assertRaises(ValueError, os.spawnve, os.P_NOWAIT, args[0], [], {})
        self.assertRaises(ValueError, os.spawnve, os.P_NOWAIT, args[0], ('',), {})
        self.assertRaises(ValueError, os.spawnve, os.P_NOWAIT, args[0], [''], {})

    def _test_invalid_env(self, spawn):
        args = [sys.executable, '-c', 'pass']

        # null character in the environment variable name
        newenv = os.environ.copy()
        newenv["FRUIT\0VEGETABLE"] = "cabbage"
        try:
            exitcode = spawn(os.P_WAIT, args[0], args, newenv)
        except ValueError:
            pass
        else:
            self.assertEqual(exitcode, 127)

        # null character in the environment variable value
        newenv = os.environ.copy()
        newenv["FRUIT"] = "orange\0VEGETABLE=cabbage"
        try:
            exitcode = spawn(os.P_WAIT, args[0], args, newenv)
        except ValueError:
            pass
        else:
            self.assertEqual(exitcode, 127)

        # equal character in the environment variable name
        newenv = os.environ.copy()
        newenv["FRUIT=ORANGE"] = "lemon"
        try:
            exitcode = spawn(os.P_WAIT, args[0], args, newenv)
        except ValueError:
            pass
        else:
            self.assertEqual(exitcode, 127)

        # equal character in the environment variable value
        filename = os_helper.TESTFN
        self.addCleanup(os_helper.unlink, filename)
        with open(filename, "w", encoding="utf-8") as fp:
            fp.write('import sys, os\n'
                     'if os.getenv("FRUIT") != "orange=lemon":\n'
                     '    raise AssertionError')
        args = [sys.executable, filename]
        newenv = os.environ.copy()
        newenv["FRUIT"] = "orange=lemon"
        exitcode = spawn(os.P_WAIT, args[0], args, newenv)
        self.assertEqual(exitcode, 0)

    @requires_os_func('spawnve')
    def test_spawnve_invalid_env(self):
        self._test_invalid_env(os.spawnve)

    @requires_os_func('spawnvpe')
    def test_spawnvpe_invalid_env(self):
        self._test_invalid_env(os.spawnvpe)


# The introduction of this TestCase caused at least two different errors on
# *nix buildbots. Temporarily skip this to let the buildbots move along.
@unittest.skip("Skip due to platform/environment differences on *NIX buildbots")
@unittest.skipUnless(hasattr(os, 'getlogin'), "test needs os.getlogin")
class LoginTests(unittest.TestCase):
    def test_getlogin(self):
        user_name = os.getlogin()
        self.assertNotEqual(len(user_name), 0)


@unittest.skipUnless(hasattr(os, 'getpriority') and hasattr(os, 'setpriority'),
                     "needs os.getpriority and os.setpriority")
class ProgramPriorityTests(unittest.TestCase):
    """Tests for os.getpriority() and os.setpriority()."""

    def test_set_get_priority(self):

        base = os.getpriority(os.PRIO_PROCESS, os.getpid())
        os.setpriority(os.PRIO_PROCESS, os.getpid(), base + 1)
        try:
            new_prio = os.getpriority(os.PRIO_PROCESS, os.getpid())
            if base >= 19 and new_prio <= 19:
                raise unittest.SkipTest("unable to reliably test setpriority "
                                        "at current nice level of %s" % base)
            else:
                self.assertEqual(new_prio, base + 1)
        finally:
            try:
                os.setpriority(os.PRIO_PROCESS, os.getpid(), base)
            except OSError as err:
                if err.errno != errno.EACCES:
                    raise


@unittest.skipUnless(hasattr(os, 'sendfile'), "test needs os.sendfile()")
class TestSendfile(unittest.IsolatedAsyncioTestCase):

    DATA = b"12345abcde" * 16 * 1024  # 160 KiB
    SUPPORT_HEADERS_TRAILERS = not sys.platform.startswith("linux") and \
                               not sys.platform.startswith("solaris") and \
                               not sys.platform.startswith("sunos")
    requires_headers_trailers = unittest.skipUnless(SUPPORT_HEADERS_TRAILERS,
            'requires headers and trailers support')
    requires_32b = unittest.skipUnless(sys.maxsize < 2**32,
            'test is only meaningful on 32-bit builds')

    @classmethod
    def setUpClass(cls):
        create_file(os_helper.TESTFN, cls.DATA)

    @classmethod
    def tearDownClass(cls):
        os_helper.unlink(os_helper.TESTFN)

    @staticmethod
    async def chunks(reader):
        while not reader.at_eof():
            yield await reader.read()

    async def handle_new_client(self, reader, writer):
        self.server_buffer = b''.join([x async for x in self.chunks(reader)])
        writer.close()
        self.server.close()  # The test server processes a single client only

    async def asyncSetUp(self):
        self.server_buffer = b''
        self.server = await asyncio.start_server(self.handle_new_client,
                                                 socket_helper.HOSTv4)
        server_name = self.server.sockets[0].getsockname()
        self.client = socket.socket()
        self.client.setblocking(False)
        await asyncio.get_running_loop().sock_connect(self.client, server_name)
        self.sockno = self.client.fileno()
        self.file = open(os_helper.TESTFN, 'rb')
        self.fileno = self.file.fileno()

    async def asyncTearDown(self):
        self.file.close()
        self.client.close()
        await self.server.wait_closed()

    # Use the test subject instead of asyncio.loop.sendfile
    @staticmethod
    async def async_sendfile(*args, **kwargs):
        return await asyncio.to_thread(os.sendfile, *args, **kwargs)

    @staticmethod
    async def sendfile_wrapper(*args, **kwargs):
        """A higher level wrapper representing how an application is
        supposed to use sendfile().
        """
        while True:
            try:
                return await TestSendfile.async_sendfile(*args, **kwargs)
            except OSError as err:
                if err.errno == errno.ECONNRESET:
                    # disconnected
                    raise
                elif err.errno in (errno.EAGAIN, errno.EBUSY):
                    # we have to retry send data
                    continue
                else:
                    raise

    async def test_send_whole_file(self):
        # normal send
        total_sent = 0
        offset = 0
        nbytes = 4096
        while total_sent < len(self.DATA):
            sent = await self.sendfile_wrapper(self.sockno, self.fileno,
                                               offset, nbytes)
            if sent == 0:
                break
            offset += sent
            total_sent += sent
            self.assertTrue(sent <= nbytes)
            self.assertEqual(offset, total_sent)

        self.assertEqual(total_sent, len(self.DATA))
        self.client.shutdown(socket.SHUT_RDWR)
        self.client.close()
        await self.server.wait_closed()
        self.assertEqual(len(self.server_buffer), len(self.DATA))
        self.assertEqual(self.server_buffer, self.DATA)

    async def test_send_at_certain_offset(self):
        # start sending a file at a certain offset
        total_sent = 0
        offset = len(self.DATA) // 2
        must_send = len(self.DATA) - offset
        nbytes = 4096
        while total_sent < must_send:
            sent = await self.sendfile_wrapper(self.sockno, self.fileno,
                                               offset, nbytes)
            if sent == 0:
                break
            offset += sent
            total_sent += sent
            self.assertTrue(sent <= nbytes)

        self.client.shutdown(socket.SHUT_RDWR)
        self.client.close()
        await self.server.wait_closed()
        expected = self.DATA[len(self.DATA) // 2:]
        self.assertEqual(total_sent, len(expected))
        self.assertEqual(len(self.server_buffer), len(expected))
        self.assertEqual(self.server_buffer, expected)

    async def test_offset_overflow(self):
        # specify an offset > file size
        offset = len(self.DATA) + 4096
        try:
            sent = await self.async_sendfile(self.sockno, self.fileno,
                                             offset, 4096)
        except OSError as e:
            # Solaris can raise EINVAL if offset >= file length, ignore.
            if e.errno != errno.EINVAL:
                raise
        else:
            self.assertEqual(sent, 0)
        self.client.shutdown(socket.SHUT_RDWR)
        self.client.close()
        await self.server.wait_closed()
        self.assertEqual(self.server_buffer, b'')

    async def test_invalid_offset(self):
        with self.assertRaises(OSError) as cm:
            await self.async_sendfile(self.sockno, self.fileno, -1, 4096)
        self.assertEqual(cm.exception.errno, errno.EINVAL)

    async def test_keywords(self):
        # Keyword arguments should be supported
        await self.async_sendfile(out_fd=self.sockno, in_fd=self.fileno,
                                  offset=0, count=4096)
        if self.SUPPORT_HEADERS_TRAILERS:
            await self.async_sendfile(out_fd=self.sockno, in_fd=self.fileno,
                                      offset=0, count=4096,
                                      headers=(), trailers=(), flags=0)

    # --- headers / trailers tests

    @requires_headers_trailers
    async def test_headers(self):
        total_sent = 0
        expected_data = b"x" * 512 + b"y" * 256 + self.DATA[:-1]
        sent = await self.async_sendfile(self.sockno, self.fileno, 0, 4096,
                                         headers=[b"x" * 512, b"y" * 256])
        self.assertLessEqual(sent, 512 + 256 + 4096)
        total_sent += sent
        offset = 4096
        while total_sent < len(expected_data):
            nbytes = min(len(expected_data) - total_sent, 4096)
            sent = await self.sendfile_wrapper(self.sockno, self.fileno,
                                               offset, nbytes)
            if sent == 0:
                break
            self.assertLessEqual(sent, nbytes)
            total_sent += sent
            offset += sent

        self.assertEqual(total_sent, len(expected_data))
        self.client.close()
        await self.server.wait_closed()
        self.assertEqual(hash(self.server_buffer), hash(expected_data))

    @requires_headers_trailers
    async def test_trailers(self):
        TESTFN2 = os_helper.TESTFN + "2"
        file_data = b"abcdef"

        self.addCleanup(os_helper.unlink, TESTFN2)
        create_file(TESTFN2, file_data)

        with open(TESTFN2, 'rb') as f:
            await self.async_sendfile(self.sockno, f.fileno(), 0, 5,
                                      trailers=[b"123456", b"789"])
            self.client.close()
            await self.server.wait_closed()
            self.assertEqual(self.server_buffer, b"abcde123456789")

    @requires_headers_trailers
    @requires_32b
    async def test_headers_overflow_32bits(self):
        self.server.handler_instance.accumulate = False
        with self.assertRaises(OSError) as cm:
            await self.async_sendfile(self.sockno, self.fileno, 0, 0,
                                      headers=[b"x" * 2**16] * 2**15)
        self.assertEqual(cm.exception.errno, errno.EINVAL)

    @requires_headers_trailers
    @requires_32b
    async def test_trailers_overflow_32bits(self):
        self.server.handler_instance.accumulate = False
        with self.assertRaises(OSError) as cm:
            await self.async_sendfile(self.sockno, self.fileno, 0, 0,
                                      trailers=[b"x" * 2**16] * 2**15)
        self.assertEqual(cm.exception.errno, errno.EINVAL)

    @requires_headers_trailers
    @unittest.skipUnless(hasattr(os, 'SF_NODISKIO'),
                         'test needs os.SF_NODISKIO')
    async def test_flags(self):
        try:
            await self.async_sendfile(self.sockno, self.fileno, 0, 4096,
                                      flags=os.SF_NODISKIO)
        except OSError as err:
            if err.errno not in (errno.EBUSY, errno.EAGAIN):
                raise


def supports_extended_attributes():
    if not hasattr(os, "setxattr"):
        return False

    try:
        with open(os_helper.TESTFN, "xb", 0) as fp:
            try:
                os.setxattr(fp.fileno(), b"user.test", b"")
            except OSError:
                return False
    finally:
        os_helper.unlink(os_helper.TESTFN)

    return True


@unittest.skipUnless(supports_extended_attributes(),
                     "no non-broken extended attribute support")
# Kernels < 2.6.39 don't respect setxattr flags.
@support.requires_linux_version(2, 6, 39)
class ExtendedAttributeTests(unittest.TestCase):

    def _check_xattrs_str(self, s, getxattr, setxattr, removexattr, listxattr, **kwargs):
        fn = os_helper.TESTFN
        self.addCleanup(os_helper.unlink, fn)
        create_file(fn)

        with self.assertRaises(OSError) as cm:
            getxattr(fn, s("user.test"), **kwargs)
        self.assertEqual(cm.exception.errno, errno.ENODATA)

        init_xattr = listxattr(fn)
        self.assertIsInstance(init_xattr, list)

        setxattr(fn, s("user.test"), b"", **kwargs)
        xattr = set(init_xattr)
        xattr.add("user.test")
        self.assertEqual(set(listxattr(fn)), xattr)
        self.assertEqual(getxattr(fn, b"user.test", **kwargs), b"")
        setxattr(fn, s("user.test"), b"hello", os.XATTR_REPLACE, **kwargs)
        self.assertEqual(getxattr(fn, b"user.test", **kwargs), b"hello")

        with self.assertRaises(OSError) as cm:
            setxattr(fn, s("user.test"), b"bye", os.XATTR_CREATE, **kwargs)
        self.assertEqual(cm.exception.errno, errno.EEXIST)

        with self.assertRaises(OSError) as cm:
            setxattr(fn, s("user.test2"), b"bye", os.XATTR_REPLACE, **kwargs)
        self.assertEqual(cm.exception.errno, errno.ENODATA)

        setxattr(fn, s("user.test2"), b"foo", os.XATTR_CREATE, **kwargs)
        xattr.add("user.test2")
        self.assertEqual(set(listxattr(fn)), xattr)
        removexattr(fn, s("user.test"), **kwargs)

        with self.assertRaises(OSError) as cm:
            getxattr(fn, s("user.test"), **kwargs)
        self.assertEqual(cm.exception.errno, errno.ENODATA)

        xattr.remove("user.test")
        self.assertEqual(set(listxattr(fn)), xattr)
        self.assertEqual(getxattr(fn, s("user.test2"), **kwargs), b"foo")
        setxattr(fn, s("user.test"), b"a"*1024, **kwargs)
        self.assertEqual(getxattr(fn, s("user.test"), **kwargs), b"a"*1024)
        removexattr(fn, s("user.test"), **kwargs)
        many = sorted("user.test{}".format(i) for i in range(100))
        for thing in many:
            setxattr(fn, thing, b"x", **kwargs)
        self.assertEqual(set(listxattr(fn)), set(init_xattr) | set(many))

    def _check_xattrs(self, *args, **kwargs):
        self._check_xattrs_str(str, *args, **kwargs)
        os_helper.unlink(os_helper.TESTFN)

        self._check_xattrs_str(os.fsencode, *args, **kwargs)
        os_helper.unlink(os_helper.TESTFN)

    def test_simple(self):
        self._check_xattrs(os.getxattr, os.setxattr, os.removexattr,
                           os.listxattr)

    def test_lpath(self):
        self._check_xattrs(os.getxattr, os.setxattr, os.removexattr,
                           os.listxattr, follow_symlinks=False)

    def test_fds(self):
        def getxattr(path, *args):
            with open(path, "rb") as fp:
                return os.getxattr(fp.fileno(), *args)
        def setxattr(path, *args):
            with open(path, "wb", 0) as fp:
                os.setxattr(fp.fileno(), *args)
        def removexattr(path, *args):
            with open(path, "wb", 0) as fp:
                os.removexattr(fp.fileno(), *args)
        def listxattr(path, *args):
            with open(path, "rb") as fp:
                return os.listxattr(fp.fileno(), *args)
        self._check_xattrs(getxattr, setxattr, removexattr, listxattr)


@unittest.skipUnless(hasattr(os, 'get_terminal_size'), "requires os.get_terminal_size")
class TermsizeTests(unittest.TestCase):
    def test_does_not_crash(self):
        """Check if get_terminal_size() returns a meaningful value.

        There's no easy portable way to actually check the size of the
        terminal, so let's check if it returns something sensible instead.
        """
        try:
            size = os.get_terminal_size()
        except OSError as e:
            if sys.platform == "win32" or e.errno in (errno.EINVAL, errno.ENOTTY):
                # Under win32 a generic OSError can be thrown if the
                # handle cannot be retrieved
                self.skipTest("failed to query terminal size")
            raise

        self.assertGreaterEqual(size.columns, 0)
        self.assertGreaterEqual(size.lines, 0)

    def test_stty_match(self):
        """Check if stty returns the same results

        stty actually tests stdin, so get_terminal_size is invoked on
        stdin explicitly. If stty succeeded, then get_terminal_size()
        should work too.
        """
        try:
            size = (
                subprocess.check_output(
                    ["stty", "size"], stderr=subprocess.DEVNULL, text=True
                ).split()
            )
        except (FileNotFoundError, subprocess.CalledProcessError,
                PermissionError):
            self.skipTest("stty invocation failed")
        expected = (int(size[1]), int(size[0])) # reversed order

        try:
            actual = os.get_terminal_size(sys.__stdin__.fileno())
        except OSError as e:
            if sys.platform == "win32" or e.errno in (errno.EINVAL, errno.ENOTTY):
                # Under win32 a generic OSError can be thrown if the
                # handle cannot be retrieved
                self.skipTest("failed to query terminal size")
            raise
        self.assertEqual(expected, actual)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows specific test')
    def test_windows_fd(self):
        """Check if get_terminal_size() returns a meaningful value in Windows"""
        try:
            conout = open('conout$', 'w')
        except OSError:
            self.skipTest('failed to open conout$')
        with conout:
            size = os.get_terminal_size(conout.fileno())

        self.assertGreaterEqual(size.columns, 0)
        self.assertGreaterEqual(size.lines, 0)


@unittest.skipUnless(hasattr(os, 'memfd_create'), 'requires os.memfd_create')
@support.requires_linux_version(3, 17)
class MemfdCreateTests(unittest.TestCase):
    def test_memfd_create(self):
        fd = os.memfd_create("Hi", os.MFD_CLOEXEC)
        self.assertNotEqual(fd, -1)
        self.addCleanup(os.close, fd)
        self.assertFalse(os.get_inheritable(fd))
        with open(fd, "wb", closefd=False) as f:
            f.write(b'memfd_create')
            self.assertEqual(f.tell(), 12)

        fd2 = os.memfd_create("Hi")
        self.addCleanup(os.close, fd2)
        self.assertFalse(os.get_inheritable(fd2))


@unittest.skipUnless(hasattr(os, 'eventfd'), 'requires os.eventfd')
@support.requires_linux_version(2, 6, 30)
class EventfdTests(unittest.TestCase):
    def test_eventfd_initval(self):
        def pack(value):
            """Pack as native uint64_t
            """
            return struct.pack("@Q", value)
        size = 8  # read/write 8 bytes
        initval = 42
        fd = os.eventfd(initval)
        self.assertNotEqual(fd, -1)
        self.addCleanup(os.close, fd)
        self.assertFalse(os.get_inheritable(fd))

        # test with raw read/write
        res = os.read(fd, size)
        self.assertEqual(res, pack(initval))

        os.write(fd, pack(23))
        res = os.read(fd, size)
        self.assertEqual(res, pack(23))

        os.write(fd, pack(40))
        os.write(fd, pack(2))
        res = os.read(fd, size)
        self.assertEqual(res, pack(42))

        # test with eventfd_read/eventfd_write
        os.eventfd_write(fd, 20)
        os.eventfd_write(fd, 3)
        res = os.eventfd_read(fd)
        self.assertEqual(res, 23)

    def test_eventfd_semaphore(self):
        initval = 2
        flags = os.EFD_CLOEXEC | os.EFD_SEMAPHORE | os.EFD_NONBLOCK
        fd = os.eventfd(initval, flags)
        self.assertNotEqual(fd, -1)
        self.addCleanup(os.close, fd)

        # semaphore starts has initval 2, two reads return '1'
        res = os.eventfd_read(fd)
        self.assertEqual(res, 1)
        res = os.eventfd_read(fd)
        self.assertEqual(res, 1)
        # third read would block
        with self.assertRaises(BlockingIOError):
            os.eventfd_read(fd)
        with self.assertRaises(BlockingIOError):
            os.read(fd, 8)

        # increase semaphore counter, read one
        os.eventfd_write(fd, 1)
        res = os.eventfd_read(fd)
        self.assertEqual(res, 1)
        # next read would block, too
        with self.assertRaises(BlockingIOError):
            os.eventfd_read(fd)

    def test_eventfd_select(self):
        flags = os.EFD_CLOEXEC | os.EFD_NONBLOCK
        fd = os.eventfd(0, flags)
        self.assertNotEqual(fd, -1)
        self.addCleanup(os.close, fd)

        # counter is zero, only writeable
        rfd, wfd, xfd = select.select([fd], [fd], [fd], 0)
        self.assertEqual((rfd, wfd, xfd), ([], [fd], []))

        # counter is non-zero, read and writeable
        os.eventfd_write(fd, 23)
        rfd, wfd, xfd = select.select([fd], [fd], [fd], 0)
        self.assertEqual((rfd, wfd, xfd), ([fd], [fd], []))
        self.assertEqual(os.eventfd_read(fd), 23)

        # counter at max, only readable
        os.eventfd_write(fd, (2**64) - 2)
        rfd, wfd, xfd = select.select([fd], [fd], [fd], 0)
        self.assertEqual((rfd, wfd, xfd), ([fd], [], []))
        os.eventfd_read(fd)


class OSErrorTests(unittest.TestCase):
    def setUp(self):
        class Str(str):
            pass

        self.bytes_filenames = []
        self.unicode_filenames = []
        if os_helper.TESTFN_UNENCODABLE is not None:
            decoded = os_helper.TESTFN_UNENCODABLE
        else:
            decoded = os_helper.TESTFN
        self.unicode_filenames.append(decoded)
        self.unicode_filenames.append(Str(decoded))
        if os_helper.TESTFN_UNDECODABLE is not None:
            encoded = os_helper.TESTFN_UNDECODABLE
        else:
            encoded = os.fsencode(os_helper.TESTFN)
        self.bytes_filenames.append(encoded)

        self.filenames = self.bytes_filenames + self.unicode_filenames

    def test_oserror_filename(self):
        funcs = [
            (self.filenames, os.chdir,),
            (self.filenames, os.lstat,),
            (self.filenames, os.open, os.O_RDONLY),
            (self.filenames, os.rmdir,),
            (self.filenames, os.stat,),
            (self.filenames, os.unlink,),
            (self.filenames, os.listdir,),
            (self.filenames, os.rename, "dst"),
            (self.filenames, os.replace, "dst"),
        ]
        if os_helper.can_chmod():
            funcs.append((self.filenames, os.chmod, 0o777))
        if hasattr(os, "chown"):
            funcs.append((self.filenames, os.chown, 0, 0))
        if hasattr(os, "lchown"):
            funcs.append((self.filenames, os.lchown, 0, 0))
        if hasattr(os, "truncate"):
            funcs.append((self.filenames, os.truncate, 0))
        if hasattr(os, "chflags"):
            funcs.append((self.filenames, os.chflags, 0))
        if hasattr(os, "lchflags"):
            funcs.append((self.filenames, os.lchflags, 0))
        if hasattr(os, "chroot"):
            funcs.append((self.filenames, os.chroot,))
        if hasattr(os, "link"):
            funcs.append((self.filenames, os.link, "dst"))
        if hasattr(os, "listxattr"):
            funcs.extend((
                (self.filenames, os.listxattr,),
                (self.filenames, os.getxattr, "user.test"),
                (self.filenames, os.setxattr, "user.test", b'user'),
                (self.filenames, os.removexattr, "user.test"),
            ))
        if hasattr(os, "lchmod"):
            funcs.append((self.filenames, os.lchmod, 0o777))
        if hasattr(os, "readlink"):
            funcs.append((self.filenames, os.readlink,))

        for filenames, func, *func_args in funcs:
            for name in filenames:
                try:
                    func(name, *func_args)
                except OSError as err:
                    self.assertIs(err.filename, name, str(func))
                except UnicodeDecodeError:
                    pass
                else:
                    self.fail(f"No exception thrown by {func}")

class CPUCountTests(unittest.TestCase):
    def test_cpu_count(self):
        cpus = os.cpu_count()
        if cpus is not None:
            self.assertIsInstance(cpus, int)
            self.assertGreater(cpus, 0)
        else:
            self.skipTest("Could not determine the number of CPUs")


# FD inheritance check is only useful for systems with process support.
@support.requires_subprocess()
class FDInheritanceTests(unittest.TestCase):
    def test_get_set_inheritable(self):
        fd = os.open(__file__, os.O_RDONLY)
        self.addCleanup(os.close, fd)
        self.assertEqual(os.get_inheritable(fd), False)

        os.set_inheritable(fd, True)
        self.assertEqual(os.get_inheritable(fd), True)

    @unittest.skipIf(fcntl is None, "need fcntl")
    def test_get_inheritable_cloexec(self):
        fd = os.open(__file__, os.O_RDONLY)
        self.addCleanup(os.close, fd)
        self.assertEqual(os.get_inheritable(fd), False)

        # clear FD_CLOEXEC flag
        flags = fcntl.fcntl(fd, fcntl.F_GETFD)
        flags &= ~fcntl.FD_CLOEXEC
        fcntl.fcntl(fd, fcntl.F_SETFD, flags)

        self.assertEqual(os.get_inheritable(fd), True)

    @unittest.skipIf(fcntl is None, "need fcntl")
    def test_set_inheritable_cloexec(self):
        fd = os.open(__file__, os.O_RDONLY)
        self.addCleanup(os.close, fd)
        self.assertEqual(fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC,
                         fcntl.FD_CLOEXEC)

        os.set_inheritable(fd, True)
        self.assertEqual(fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC,
                         0)

    @unittest.skipUnless(hasattr(os, 'O_PATH'), "need os.O_PATH")
    def test_get_set_inheritable_o_path(self):
        fd = os.open(__file__, os.O_PATH)
        self.addCleanup(os.close, fd)
        self.assertEqual(os.get_inheritable(fd), False)

        os.set_inheritable(fd, True)
        self.assertEqual(os.get_inheritable(fd), True)

        os.set_inheritable(fd, False)
        self.assertEqual(os.get_inheritable(fd), False)

    def test_get_set_inheritable_badf(self):
        fd = os_helper.make_bad_fd()

        with self.assertRaises(OSError) as ctx:
            os.get_inheritable(fd)
        self.assertEqual(ctx.exception.errno, errno.EBADF)

        with self.assertRaises(OSError) as ctx:
            os.set_inheritable(fd, True)
        self.assertEqual(ctx.exception.errno, errno.EBADF)

        with self.assertRaises(OSError) as ctx:
            os.set_inheritable(fd, False)
        self.assertEqual(ctx.exception.errno, errno.EBADF)

    def test_open(self):
        fd = os.open(__file__, os.O_RDONLY)
        self.addCleanup(os.close, fd)
        self.assertEqual(os.get_inheritable(fd), False)

    @unittest.skipUnless(hasattr(os, 'pipe'), "need os.pipe()")
    def test_pipe(self):
        rfd, wfd = os.pipe()
        self.addCleanup(os.close, rfd)
        self.addCleanup(os.close, wfd)
        self.assertEqual(os.get_inheritable(rfd), False)
        self.assertEqual(os.get_inheritable(wfd), False)

    def test_dup(self):
        fd1 = os.open(__file__, os.O_RDONLY)
        self.addCleanup(os.close, fd1)

        fd2 = os.dup(fd1)
        self.addCleanup(os.close, fd2)
        self.assertEqual(os.get_inheritable(fd2), False)

    def test_dup_standard_stream(self):
        fd = os.dup(1)
        self.addCleanup(os.close, fd)
        self.assertGreater(fd, 0)

    @unittest.skipUnless(sys.platform == 'win32', 'win32-specific test')
    def test_dup_nul(self):
        # os.dup() was creating inheritable fds for character files.
        fd1 = os.open('NUL', os.O_RDONLY)
        self.addCleanup(os.close, fd1)
        fd2 = os.dup(fd1)
        self.addCleanup(os.close, fd2)
        self.assertFalse(os.get_inheritable(fd2))

    @unittest.skipUnless(hasattr(os, 'dup2'), "need os.dup2()")
    def test_dup2(self):
        fd = os.open(__file__, os.O_RDONLY)
        self.addCleanup(os.close, fd)

        # inheritable by default
        fd2 = os.open(__file__, os.O_RDONLY)
        self.addCleanup(os.close, fd2)
        self.assertEqual(os.dup2(fd, fd2), fd2)
        self.assertTrue(os.get_inheritable(fd2))

        # force non-inheritable
        fd3 = os.open(__file__, os.O_RDONLY)
        self.addCleanup(os.close, fd3)
        self.assertEqual(os.dup2(fd, fd3, inheritable=False), fd3)
        self.assertFalse(os.get_inheritable(fd3))

    @unittest.skipUnless(hasattr(os, 'openpty'), "need os.openpty()")
    def test_openpty(self):
        master_fd, slave_fd = os.openpty()
        self.addCleanup(os.close, master_fd)
        self.addCleanup(os.close, slave_fd)
        self.assertEqual(os.get_inheritable(master_fd), False)
        self.assertEqual(os.get_inheritable(slave_fd), False)


class PathTConverterTests(unittest.TestCase):
    # tuples of (function name, allows fd arguments, additional arguments to
    # function, cleanup function)
    functions = [
        ('stat', True, (), None),
        ('lstat', False, (), None),
        ('access', False, (os.F_OK,), None),
        ('chflags', False, (0,), None),
        ('lchflags', False, (0,), None),
        ('open', False, (os.O_RDONLY,), getattr(os, 'close', None)),
    ]

    def test_path_t_converter(self):
        str_filename = os_helper.TESTFN
        if os.name == 'nt':
            bytes_fspath = bytes_filename = None
        else:
            bytes_filename = os.fsencode(os_helper.TESTFN)
            bytes_fspath = FakePath(bytes_filename)
        fd = os.open(FakePath(str_filename), os.O_WRONLY|os.O_CREAT)
        self.addCleanup(os_helper.unlink, os_helper.TESTFN)
        self.addCleanup(os.close, fd)

        int_fspath = FakePath(fd)
        str_fspath = FakePath(str_filename)

        for name, allow_fd, extra_args, cleanup_fn in self.functions:
            with self.subTest(name=name):
                try:
                    fn = getattr(os, name)
                except AttributeError:
                    continue

                for path in (str_filename, bytes_filename, str_fspath,
                             bytes_fspath):
                    if path is None:
                        continue
                    with self.subTest(name=name, path=path):
                        result = fn(path, *extra_args)
                        if cleanup_fn is not None:
                            cleanup_fn(result)

                with self.assertRaisesRegex(
                        TypeError, 'to return str or bytes'):
                    fn(int_fspath, *extra_args)

                if allow_fd:
                    result = fn(fd, *extra_args)  # should not fail
                    if cleanup_fn is not None:
                        cleanup_fn(result)
                else:
                    with self.assertRaisesRegex(
                            TypeError,
                            'os.PathLike'):
                        fn(fd, *extra_args)

    def test_path_t_converter_and_custom_class(self):
        msg = r'__fspath__\(\) to return str or bytes, not %s'
        with self.assertRaisesRegex(TypeError, msg % r'int'):
            os.stat(FakePath(2))
        with self.assertRaisesRegex(TypeError, msg % r'float'):
            os.stat(FakePath(2.34))
        with self.assertRaisesRegex(TypeError, msg % r'object'):
            os.stat(FakePath(object()))


@unittest.skipUnless(hasattr(os, 'get_blocking'),
                     'needs os.get_blocking() and os.set_blocking()')
@unittest.skipIf(support.is_emscripten, "Cannot unset blocking flag")
@unittest.skipIf(sys.platform == 'win32', 'Windows only supports blocking on pipes')
class BlockingTests(unittest.TestCase):
    def test_blocking(self):
        fd = os.open(__file__, os.O_RDONLY)
        self.addCleanup(os.close, fd)
        self.assertEqual(os.get_blocking(fd), True)

        os.set_blocking(fd, False)
        self.assertEqual(os.get_blocking(fd), False)

        os.set_blocking(fd, True)
        self.assertEqual(os.get_blocking(fd), True)



class ExportsTests(unittest.TestCase):
    def test_os_all(self):
        self.assertIn('open', os.__all__)
        self.assertIn('walk', os.__all__)


class TestDirEntry(unittest.TestCase):
    def setUp(self):
        self.path = os.path.realpath(os_helper.TESTFN)
        self.addCleanup(os_helper.rmtree, self.path)
        os.mkdir(self.path)

    def test_uninstantiable(self):
        self.assertRaises(TypeError, os.DirEntry)

    def test_unpickable(self):
        filename = create_file(os.path.join(self.path, "file.txt"), b'python')
        entry = [entry for entry in os.scandir(self.path)].pop()
        self.assertIsInstance(entry, os.DirEntry)
        self.assertEqual(entry.name, "file.txt")
        import pickle
        self.assertRaises(TypeError, pickle.dumps, entry, filename)


class TestScandir(unittest.TestCase):
    check_no_resource_warning = warnings_helper.check_no_resource_warning

    def setUp(self):
        self.path = os.path.realpath(os_helper.TESTFN)
        self.bytes_path = os.fsencode(self.path)
        self.addCleanup(os_helper.rmtree, self.path)
        os.mkdir(self.path)

    def create_file(self, name="file.txt"):
        path = self.bytes_path if isinstance(name, bytes) else self.path
        filename = os.path.join(path, name)
        create_file(filename, b'python')
        return filename

    def get_entries(self, names):
        entries = dict((entry.name, entry)
                       for entry in os.scandir(self.path))
        self.assertEqual(sorted(entries.keys()), names)
        return entries

    def assert_stat_equal(self, stat1, stat2, skip_fields):
        if skip_fields:
            for attr in dir(stat1):
                if not attr.startswith("st_"):
                    continue
                if attr in ("st_dev", "st_ino", "st_nlink"):
                    continue
                self.assertEqual(getattr(stat1, attr),
                                 getattr(stat2, attr),
                                 (stat1, stat2, attr))
        else:
            self.assertEqual(stat1, stat2)

    def test_uninstantiable(self):
        scandir_iter = os.scandir(self.path)
        self.assertRaises(TypeError, type(scandir_iter))
        scandir_iter.close()

    def test_unpickable(self):
        filename = self.create_file("file.txt")
        scandir_iter = os.scandir(self.path)
        import pickle
        self.assertRaises(TypeError, pickle.dumps, scandir_iter, filename)
        scandir_iter.close()

    def check_entry(self, entry, name, is_dir, is_file, is_symlink):
        self.assertIsInstance(entry, os.DirEntry)
        self.assertEqual(entry.name, name)
        self.assertEqual(entry.path, os.path.join(self.path, name))
        self.assertEqual(entry.inode(),
                         os.stat(entry.path, follow_symlinks=False).st_ino)

        entry_stat = os.stat(entry.path)
        self.assertEqual(entry.is_dir(),
                         stat.S_ISDIR(entry_stat.st_mode))
        self.assertEqual(entry.is_file(),
                         stat.S_ISREG(entry_stat.st_mode))
        self.assertEqual(entry.is_symlink(),
                         os.path.islink(entry.path))

        entry_lstat = os.stat(entry.path, follow_symlinks=False)
        self.assertEqual(entry.is_dir(follow_symlinks=False),
                         stat.S_ISDIR(entry_lstat.st_mode))
        self.assertEqual(entry.is_file(follow_symlinks=False),
                         stat.S_ISREG(entry_lstat.st_mode))

        self.assertEqual(entry.is_junction(), os.path.isjunction(entry.path))

        self.assert_stat_equal(entry.stat(),
                               entry_stat,
                               os.name == 'nt' and not is_symlink)
        self.assert_stat_equal(entry.stat(follow_symlinks=False),
                               entry_lstat,
                               os.name == 'nt')

    def test_attributes(self):
        link = hasattr(os, 'link')
        symlink = os_helper.can_symlink()

        dirname = os.path.join(self.path, "dir")
        os.mkdir(dirname)
        filename = self.create_file("file.txt")
        if link:
            try:
                os.link(filename, os.path.join(self.path, "link_file.txt"))
            except PermissionError as e:
                self.skipTest('os.link(): %s' % e)
        if symlink:
            os.symlink(dirname, os.path.join(self.path, "symlink_dir"),
                       target_is_directory=True)
            os.symlink(filename, os.path.join(self.path, "symlink_file.txt"))

        names = ['dir', 'file.txt']
        if link:
            names.append('link_file.txt')
        if symlink:
            names.extend(('symlink_dir', 'symlink_file.txt'))
        entries = self.get_entries(names)

        entry = entries['dir']
        self.check_entry(entry, 'dir', True, False, False)

        entry = entries['file.txt']
        self.check_entry(entry, 'file.txt', False, True, False)

        if link:
            entry = entries['link_file.txt']
            self.check_entry(entry, 'link_file.txt', False, True, False)

        if symlink:
            entry = entries['symlink_dir']
            self.check_entry(entry, 'symlink_dir', True, False, True)

            entry = entries['symlink_file.txt']
            self.check_entry(entry, 'symlink_file.txt', False, True, True)

    @unittest.skipIf(sys.platform != 'win32', "Can only test junctions with creation on win32.")
    def test_attributes_junctions(self):
        dirname = os.path.join(self.path, "tgtdir")
        os.mkdir(dirname)

        import _winapi
        try:
            _winapi.CreateJunction(dirname, os.path.join(self.path, "srcjunc"))
        except OSError:
            raise unittest.SkipTest('creating the test junction failed')

        entries = self.get_entries(['srcjunc', 'tgtdir'])
        self.assertEqual(entries['srcjunc'].is_junction(), True)
        self.assertEqual(entries['tgtdir'].is_junction(), False)

    def get_entry(self, name):
        path = self.bytes_path if isinstance(name, bytes) else self.path
        entries = list(os.scandir(path))
        self.assertEqual(len(entries), 1)

        entry = entries[0]
        self.assertEqual(entry.name, name)
        return entry

    def create_file_entry(self, name='file.txt'):
        filename = self.create_file(name=name)
        return self.get_entry(os.path.basename(filename))

    def test_current_directory(self):
        filename = self.create_file()
        old_dir = os.getcwd()
        try:
            os.chdir(self.path)

            # call scandir() without parameter: it must list the content
            # of the current directory
            entries = dict((entry.name, entry) for entry in os.scandir())
            self.assertEqual(sorted(entries.keys()),
                             [os.path.basename(filename)])
        finally:
            os.chdir(old_dir)

    def test_repr(self):
        entry = self.create_file_entry()
        self.assertEqual(repr(entry), "<DirEntry 'file.txt'>")

    def test_fspath_protocol(self):
        entry = self.create_file_entry()
        self.assertEqual(os.fspath(entry), os.path.join(self.path, 'file.txt'))

    def test_fspath_protocol_bytes(self):
        bytes_filename = os.fsencode('bytesfile.txt')
        bytes_entry = self.create_file_entry(name=bytes_filename)
        fspath = os.fspath(bytes_entry)
        self.assertIsInstance(fspath, bytes)
        self.assertEqual(fspath,
                         os.path.join(os.fsencode(self.path),bytes_filename))

    def test_removed_dir(self):
        path = os.path.join(self.path, 'dir')

        os.mkdir(path)
        entry = self.get_entry('dir')
        os.rmdir(path)

        # On POSIX, is_dir() result depends if scandir() filled d_type or not
        if os.name == 'nt':
            self.assertTrue(entry.is_dir())
        self.assertFalse(entry.is_file())
        self.assertFalse(entry.is_symlink())
        if os.name == 'nt':
            self.assertRaises(FileNotFoundError, entry.inode)
            # don't fail
            entry.stat()
            entry.stat(follow_symlinks=False)
        else:
            self.assertGreater(entry.inode(), 0)
            self.assertRaises(FileNotFoundError, entry.stat)
            self.assertRaises(FileNotFoundError, entry.stat, follow_symlinks=False)

    def test_removed_file(self):
        entry = self.create_file_entry()
        os.unlink(entry.path)

        self.assertFalse(entry.is_dir())
        # On POSIX, is_dir() result depends if scandir() filled d_type or not
        if os.name == 'nt':
            self.assertTrue(entry.is_file())
        self.assertFalse(entry.is_symlink())
        if os.name == 'nt':
            self.assertRaises(FileNotFoundError, entry.inode)
            # don't fail
            entry.stat()
            entry.stat(follow_symlinks=False)
        else:
            self.assertGreater(entry.inode(), 0)
            self.assertRaises(FileNotFoundError, entry.stat)
            self.assertRaises(FileNotFoundError, entry.stat, follow_symlinks=False)

    def test_broken_symlink(self):
        if not os_helper.can_symlink():
            return self.skipTest('cannot create symbolic link')

        filename = self.create_file("file.txt")
        os.symlink(filename,
                   os.path.join(self.path, "symlink.txt"))
        entries = self.get_entries(['file.txt', 'symlink.txt'])
        entry = entries['symlink.txt']
        os.unlink(filename)

        self.assertGreater(entry.inode(), 0)
        self.assertFalse(entry.is_dir())
        self.assertFalse(entry.is_file())  # broken symlink returns False
        self.assertFalse(entry.is_dir(follow_symlinks=False))
        self.assertFalse(entry.is_file(follow_symlinks=False))
        self.assertTrue(entry.is_symlink())
        self.assertRaises(FileNotFoundError, entry.stat)
        # don't fail
        entry.stat(follow_symlinks=False)

    def test_bytes(self):
        self.create_file("file.txt")

        path_bytes = os.fsencode(self.path)
        entries = list(os.scandir(path_bytes))
        self.assertEqual(len(entries), 1, entries)
        entry = entries[0]

        self.assertEqual(entry.name, b'file.txt')
        self.assertEqual(entry.path,
                         os.fsencode(os.path.join(self.path, 'file.txt')))

    def test_bytes_like(self):
        self.create_file("file.txt")

        for cls in bytearray, memoryview:
            path_bytes = cls(os.fsencode(self.path))
            with self.assertRaises(TypeError):
                os.scandir(path_bytes)

    @unittest.skipUnless(os.listdir in os.supports_fd,
                         'fd support for listdir required for this test.')
    def test_fd(self):
        self.assertIn(os.scandir, os.supports_fd)
        self.create_file('file.txt')
        expected_names = ['file.txt']
        if os_helper.can_symlink():
            os.symlink('file.txt', os.path.join(self.path, 'link'))
            expected_names.append('link')

        with os_helper.open_dir_fd(self.path) as fd:
            with os.scandir(fd) as it:
                entries = list(it)
            names = [entry.name for entry in entries]
            self.assertEqual(sorted(names), expected_names)
            self.assertEqual(names, os.listdir(fd))
            for entry in entries:
                self.assertEqual(entry.path, entry.name)
                self.assertEqual(os.fspath(entry), entry.name)
                self.assertEqual(entry.is_symlink(), entry.name == 'link')
                if os.stat in os.supports_dir_fd:
                    st = os.stat(entry.name, dir_fd=fd)
                    self.assertEqual(entry.stat(), st)
                    st = os.stat(entry.name, dir_fd=fd, follow_symlinks=False)
                    self.assertEqual(entry.stat(follow_symlinks=False), st)

    @unittest.skipIf(support.is_wasi, "WASI maps '' to cwd")
    def test_empty_path(self):
        self.assertRaises(FileNotFoundError, os.scandir, '')

    def test_consume_iterator_twice(self):
        self.create_file("file.txt")
        iterator = os.scandir(self.path)

        entries = list(iterator)
        self.assertEqual(len(entries), 1, entries)

        # check than consuming the iterator twice doesn't raise exception
        entries2 = list(iterator)
        self.assertEqual(len(entries2), 0, entries2)

    def test_bad_path_type(self):
        for obj in [1.234, {}, []]:
            self.assertRaises(TypeError, os.scandir, obj)

    def test_close(self):
        self.create_file("file.txt")
        self.create_file("file2.txt")
        iterator = os.scandir(self.path)
        next(iterator)
        iterator.close()
        # multiple closes
        iterator.close()
        with self.check_no_resource_warning():
            del iterator

    def test_context_manager(self):
        self.create_file("file.txt")
        self.create_file("file2.txt")
        with os.scandir(self.path) as iterator:
            next(iterator)
        with self.check_no_resource_warning():
            del iterator

    def test_context_manager_close(self):
        self.create_file("file.txt")
        self.create_file("file2.txt")
        with os.scandir(self.path) as iterator:
            next(iterator)
            iterator.close()

    def test_context_manager_exception(self):
        self.create_file("file.txt")
        self.create_file("file2.txt")
        with self.assertRaises(ZeroDivisionError):
            with os.scandir(self.path) as iterator:
                next(iterator)
                1/0
        with self.check_no_resource_warning():
            del iterator

    def test_resource_warning(self):
        self.create_file("file.txt")
        self.create_file("file2.txt")
        iterator = os.scandir(self.path)
        next(iterator)
        with self.assertWarns(ResourceWarning):
            del iterator
            support.gc_collect()
        # exhausted iterator
        iterator = os.scandir(self.path)
        list(iterator)
        with self.check_no_resource_warning():
            del iterator


class TestPEP519(unittest.TestCase):

    # Abstracted so it can be overridden to test pure Python implementation
    # if a C version is provided.
    fspath = staticmethod(os.fspath)

    def test_return_bytes(self):
        for b in b'hello', b'goodbye', b'some/path/and/file':
            self.assertEqual(b, self.fspath(b))

    def test_return_string(self):
        for s in 'hello', 'goodbye', 'some/path/and/file':
            self.assertEqual(s, self.fspath(s))

    def test_fsencode_fsdecode(self):
        for p in "path/like/object", b"path/like/object":
            pathlike = FakePath(p)

            self.assertEqual(p, self.fspath(pathlike))
            self.assertEqual(b"path/like/object", os.fsencode(pathlike))
            self.assertEqual("path/like/object", os.fsdecode(pathlike))

    def test_pathlike(self):
        self.assertEqual('#feelthegil', self.fspath(FakePath('#feelthegil')))
        self.assertTrue(issubclass(FakePath, os.PathLike))
        self.assertTrue(isinstance(FakePath('x'), os.PathLike))

    def test_garbage_in_exception_out(self):
        vapor = type('blah', (), {})
        for o in int, type, os, vapor():
            self.assertRaises(TypeError, self.fspath, o)

    def test_argument_required(self):
        self.assertRaises(TypeError, self.fspath)

    def test_bad_pathlike(self):
        # __fspath__ returns a value other than str or bytes.
        self.assertRaises(TypeError, self.fspath, FakePath(42))
        # __fspath__ attribute that is not callable.
        c = type('foo', (), {})
        c.__fspath__ = 1
        self.assertRaises(TypeError, self.fspath, c())
        # __fspath__ raises an exception.
        self.assertRaises(ZeroDivisionError, self.fspath,
                          FakePath(ZeroDivisionError()))

    def test_pathlike_subclasshook(self):
        # bpo-38878: subclasshook causes subclass checks
        # true on abstract implementation.
        class A(os.PathLike):
            pass
        self.assertFalse(issubclass(FakePath, A))
        self.assertTrue(issubclass(FakePath, os.PathLike))

    def test_pathlike_class_getitem(self):
        self.assertIsInstance(os.PathLike[bytes], types.GenericAlias)


class TimesTests(unittest.TestCase):
    def test_times(self):
        times = os.times()
        self.assertIsInstance(times, os.times_result)

        for field in ('user', 'system', 'children_user', 'children_system',
                      'elapsed'):
            value = getattr(times, field)
            self.assertIsInstance(value, float)

        if os.name == 'nt':
            self.assertEqual(times.children_user, 0)
            self.assertEqual(times.children_system, 0)
            self.assertEqual(times.elapsed, 0)


@support.requires_fork()
class ForkTests(unittest.TestCase):
    def test_fork(self):
        # bpo-42540: ensure os.fork() with non-default memory allocator does
        # not crash on exit.
        code = """if 1:
            import os
            from test import support
            pid = os.fork()
            if pid != 0:
                support.wait_process(pid, exitcode=0)
        """
        assert_python_ok("-c", code)
        assert_python_ok("-c", code, PYTHONMALLOC="malloc_debug")

    @unittest.skipUnless(sys.platform in ("linux", "darwin"),
                         "Only Linux and macOS detect this today.")
    def test_fork_warns_when_non_python_thread_exists(self):
        code = """if 1:
            import os, threading, warnings
            from _testcapi import _spawn_pthread_waiter, _end_spawned_pthread
            _spawn_pthread_waiter()
            try:
                with warnings.catch_warnings(record=True) as ws:
                    warnings.filterwarnings(
                            "always", category=DeprecationWarning)
                    if os.fork() == 0:
                        assert not ws, f"unexpected warnings in child: {ws}"
                        os._exit(0)  # child
                    else:
                        assert ws[0].category == DeprecationWarning, ws[0]
                        assert 'fork' in str(ws[0].message), ws[0]
                        # Waiting allows an error in the child to hit stderr.
                        exitcode = os.wait()[1]
                        assert exitcode == 0, f"child exited {exitcode}"
                assert threading.active_count() == 1, threading.enumerate()
            finally:
                _end_spawned_pthread()
        """
        _, out, err = assert_python_ok("-c", code, PYTHONOPTIMIZE='0')
        self.assertEqual(err.decode("utf-8"), "")
        self.assertEqual(out.decode("utf-8"), "")


# Only test if the C version is provided, otherwise TestPEP519 already tested
# the pure Python implementation.
if hasattr(os, "_fspath"):
    class TestPEP519PurePython(TestPEP519):

        """Explicitly test the pure Python implementation of os.fspath()."""

        fspath = staticmethod(os._fspath)


if __name__ == "__main__":
    unittest.main()
from test import support
from test.support import import_helper, warnings_helper
import warnings
support.requires('audio')

from test.support import findfile

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    ossaudiodev = import_helper.import_module('ossaudiodev')
audioop = warnings_helper.import_deprecated('audioop')
sunau = warnings_helper.import_deprecated('sunau')

import errno
import sys
import time
import unittest

# Arggh, AFMT_S16_NE not defined on all platforms -- seems to be a
# fairly recent addition to OSS.
try:
    from ossaudiodev import AFMT_S16_NE
except ImportError:
    if sys.byteorder == "little":
        AFMT_S16_NE = ossaudiodev.AFMT_S16_LE
    else:
        AFMT_S16_NE = ossaudiodev.AFMT_S16_BE


def read_sound_file(path):
    with open(path, 'rb') as fp:
        au = sunau.open(fp)
        rate = au.getframerate()
        nchannels = au.getnchannels()
        encoding = au._encoding
        fp.seek(0)
        data = fp.read()

    if encoding != sunau.AUDIO_FILE_ENCODING_MULAW_8:
        raise RuntimeError("Expect .au file with 8-bit mu-law samples")

    # Convert the data to 16-bit signed.
    data = audioop.ulaw2lin(data, 2)
    return (data, rate, 16, nchannels)

class OSSAudioDevTests(unittest.TestCase):

    def play_sound_file(self, data, rate, ssize, nchannels):
        try:
            dsp = ossaudiodev.open('w')
        except OSError as msg:
            if msg.args[0] in (errno.EACCES, errno.ENOENT,
                               errno.ENODEV, errno.EBUSY):
                raise unittest.SkipTest(msg)
            raise

        # at least check that these methods can be invoked
        dsp.bufsize()
        dsp.obufcount()
        dsp.obuffree()
        dsp.getptr()
        dsp.fileno()

        # Make sure the read-only attributes work.
        self.assertFalse(dsp.closed)
        self.assertEqual(dsp.name, "/dev/dsp")
        self.assertEqual(dsp.mode, "w", "bad dsp.mode: %r" % dsp.mode)

        # And make sure they're really read-only.
        for attr in ('closed', 'name', 'mode'):
            try:
                setattr(dsp, attr, 42)
            except (TypeError, AttributeError):
                pass
            else:
                self.fail("dsp.%s not read-only" % attr)

        # Compute expected running time of sound sample (in seconds).
        expected_time = float(len(data)) / (ssize/8) / nchannels / rate

        # set parameters based on .au file headers
        dsp.setparameters(AFMT_S16_NE, nchannels, rate)
        self.assertTrue(abs(expected_time - 3.51) < 1e-2, expected_time)
        t1 = time.monotonic()
        dsp.write(data)
        dsp.close()
        t2 = time.monotonic()
        elapsed_time = t2 - t1

        percent_diff = (abs(elapsed_time - expected_time) / expected_time) * 100
        self.assertTrue(percent_diff <= 10.0,
                        "elapsed time (%s) > 10%% off of expected time (%s)" %
                        (elapsed_time, expected_time))

    def set_parameters(self, dsp):
        # Two configurations for testing:
        #   config1 (8-bit, mono, 8 kHz) should work on even the most
        #      ancient and crufty sound card, but maybe not on special-
        #      purpose high-end hardware
        #   config2 (16-bit, stereo, 44.1kHz) should work on all but the
        #      most ancient and crufty hardware
        config1 = (ossaudiodev.AFMT_U8, 1, 8000)
        config2 = (AFMT_S16_NE, 2, 44100)

        for config in [config1, config2]:
            (fmt, channels, rate) = config
            if (dsp.setfmt(fmt) == fmt and
                dsp.channels(channels) == channels and
                dsp.speed(rate) == rate):
                break
        else:
            raise RuntimeError("unable to set audio sampling parameters: "
                               "you must have really weird audio hardware")

        # setparameters() should be able to set this configuration in
        # either strict or non-strict mode.
        result = dsp.setparameters(fmt, channels, rate, False)
        self.assertEqual(result, (fmt, channels, rate),
                         "setparameters%r: returned %r" % (config, result))

        result = dsp.setparameters(fmt, channels, rate, True)
        self.assertEqual(result, (fmt, channels, rate),
                         "setparameters%r: returned %r" % (config, result))

    def set_bad_parameters(self, dsp):
        # Now try some configurations that are presumably bogus: eg. 300
        # channels currently exceeds even Hollywood's ambitions, and
        # negative sampling rate is utter nonsense.  setparameters() should
        # accept these in non-strict mode, returning something other than
        # was requested, but should barf in strict mode.
        fmt = AFMT_S16_NE
        rate = 44100
        channels = 2
        for config in [(fmt, 300, rate),       # ridiculous nchannels
                       (fmt, -5, rate),        # impossible nchannels
                       (fmt, channels, -50),   # impossible rate
                      ]:
            (fmt, channels, rate) = config
            result = dsp.setparameters(fmt, channels, rate, False)
            self.assertNotEqual(result, config,
                             "unexpectedly got requested configuration")

            try:
                result = dsp.setparameters(fmt, channels, rate, True)
            except ossaudiodev.OSSAudioError as err:
                pass
            else:
                self.fail("expected OSSAudioError")

    def test_playback(self):
        sound_info = read_sound_file(findfile('audiotest.au'))
        self.play_sound_file(*sound_info)

    def test_set_parameters(self):
        dsp = ossaudiodev.open("w")
        try:
            self.set_parameters(dsp)

            # Disabled because it fails under Linux 2.6 with ALSA's OSS
            # emulation layer.
            #self.set_bad_parameters(dsp)
        finally:
            dsp.close()
            self.assertTrue(dsp.closed)

    def test_mixer_methods(self):
        # Issue #8139: ossaudiodev didn't initialize its types properly,
        # therefore some methods were unavailable.
        with ossaudiodev.openmixer() as mixer:
            self.assertGreaterEqual(mixer.fileno(), 0)

    def test_with(self):
        with ossaudiodev.open('w') as dsp:
            pass
        self.assertTrue(dsp.closed)

    def test_on_closed(self):
        dsp = ossaudiodev.open('w')
        dsp.close()
        self.assertRaises(ValueError, dsp.fileno)
        self.assertRaises(ValueError, dsp.read, 1)
        self.assertRaises(ValueError, dsp.write, b'x')
        self.assertRaises(ValueError, dsp.writeall, b'x')
        self.assertRaises(ValueError, dsp.bufsize)
        self.assertRaises(ValueError, dsp.obufcount)
        self.assertRaises(ValueError, dsp.obufcount)
        self.assertRaises(ValueError, dsp.obuffree)
        self.assertRaises(ValueError, dsp.getptr)

        mixer = ossaudiodev.openmixer()
        mixer.close()
        self.assertRaises(ValueError, mixer.fileno)

def setUpModule():
    try:
        dsp = ossaudiodev.open('w')
    except (ossaudiodev.error, OSError) as msg:
        if msg.args[0] in (errno.EACCES, errno.ENOENT,
                           errno.ENODEV, errno.EBUSY):
            raise unittest.SkipTest(msg)
        raise
    dsp.close()

if __name__ == "__main__":
    unittest.main()
"""
Test suite for OS X interpreter environment variables.
"""

from test.support.os_helper import EnvironmentVarGuard
import subprocess
import sys
import sysconfig
import unittest

@unittest.skipUnless(sys.platform == 'darwin' and
                     sysconfig.get_config_var('WITH_NEXT_FRAMEWORK'),
                     'unnecessary on this platform')
class OSXEnvironmentVariableTestCase(unittest.TestCase):
    def _check_sys(self, ev, cond, sv, val = sys.executable + 'dummy'):
        with EnvironmentVarGuard() as evg:
            subpc = [str(sys.executable), '-c',
                'import sys; sys.exit(2 if "%s" %s %s else 3)' % (val, cond, sv)]
            # ensure environment variable does not exist
            evg.unset(ev)
            # test that test on sys.xxx normally fails
            rc = subprocess.call(subpc)
            self.assertEqual(rc, 3, "expected %s not %s %s" % (ev, cond, sv))
            # set environ variable
            evg.set(ev, val)
            # test that sys.xxx has been influenced by the environ value
            rc = subprocess.call(subpc)
            self.assertEqual(rc, 2, "expected %s %s %s" % (ev, cond, sv))

    def test_pythonexecutable_sets_sys_executable(self):
        self._check_sys('PYTHONEXECUTABLE', '==', 'sys.executable')

if __name__ == "__main__":
    unittest.main()
import contextlib
import collections.abc
import io
import os
import sys
import errno
import pathlib
import pickle
import socket
import stat
import tempfile
import unittest
from unittest import mock

from test.support import import_helper
from test.support import is_emscripten, is_wasi
from test.support import os_helper
from test.support.os_helper import TESTFN, FakePath

try:
    import grp, pwd
except ImportError:
    grp = pwd = None


class _BaseFlavourTest(object):

    def _check_parse_parts(self, arg, expected):
        f = self.cls._parse_parts
        sep = self.flavour.sep
        altsep = self.flavour.altsep
        actual = f([x.replace('/', sep) for x in arg])
        self.assertEqual(actual, expected)
        if altsep:
            actual = f([x.replace('/', altsep) for x in arg])
            self.assertEqual(actual, expected)

    def test_parse_parts_common(self):
        check = self._check_parse_parts
        sep = self.flavour.sep
        # Unanchored parts.
        check([],                   ('', '', []))
        check(['a'],                ('', '', ['a']))
        check(['a/'],               ('', '', ['a']))
        check(['a', 'b'],           ('', '', ['a', 'b']))
        # Expansion.
        check(['a/b'],              ('', '', ['a', 'b']))
        check(['a/b/'],             ('', '', ['a', 'b']))
        check(['a', 'b/c', 'd'],    ('', '', ['a', 'b', 'c', 'd']))
        # Collapsing and stripping excess slashes.
        check(['a', 'b//c', 'd'],   ('', '', ['a', 'b', 'c', 'd']))
        check(['a', 'b/c/', 'd'],   ('', '', ['a', 'b', 'c', 'd']))
        # Eliminating standalone dots.
        check(['.'],                ('', '', []))
        check(['.', '.', 'b'],      ('', '', ['b']))
        check(['a', '.', 'b'],      ('', '', ['a', 'b']))
        check(['a', '.', '.'],      ('', '', ['a']))
        # The first part is anchored.
        check(['/a/b'],             ('', sep, [sep, 'a', 'b']))
        check(['/a', 'b'],          ('', sep, [sep, 'a', 'b']))
        check(['/a/', 'b'],         ('', sep, [sep, 'a', 'b']))
        # Ignoring parts before an anchored part.
        check(['a', '/b', 'c'],     ('', sep, [sep, 'b', 'c']))
        check(['a', '/b', '/c'],    ('', sep, [sep, 'c']))


class PosixFlavourTest(_BaseFlavourTest, unittest.TestCase):
    cls = pathlib.PurePosixPath
    flavour = pathlib.PurePosixPath._flavour

    def test_parse_parts(self):
        check = self._check_parse_parts
        # Collapsing of excess leading slashes, except for the double-slash
        # special case.
        check(['//a', 'b'],             ('', '//', ['//', 'a', 'b']))
        check(['///a', 'b'],            ('', '/', ['/', 'a', 'b']))
        check(['////a', 'b'],           ('', '/', ['/', 'a', 'b']))
        # Paths which look like NT paths aren't treated specially.
        check(['c:a'],                  ('', '', ['c:a']))
        check(['c:\\a'],                ('', '', ['c:\\a']))
        check(['\\a'],                  ('', '', ['\\a']))


class NTFlavourTest(_BaseFlavourTest, unittest.TestCase):
    cls = pathlib.PureWindowsPath
    flavour = pathlib.PureWindowsPath._flavour

    def test_parse_parts(self):
        check = self._check_parse_parts
        # First part is anchored.
        check(['c:'],                   ('c:', '', ['c:']))
        check(['c:/'],                  ('c:', '\\', ['c:\\']))
        check(['/'],                    ('', '\\', ['\\']))
        check(['c:a'],                  ('c:', '', ['c:', 'a']))
        check(['c:/a'],                 ('c:', '\\', ['c:\\', 'a']))
        check(['/a'],                   ('', '\\', ['\\', 'a']))
        # UNC paths.
        check(['//a/b'],                ('\\\\a\\b', '\\', ['\\\\a\\b\\']))
        check(['//a/b/'],               ('\\\\a\\b', '\\', ['\\\\a\\b\\']))
        check(['//a/b/c'],              ('\\\\a\\b', '\\', ['\\\\a\\b\\', 'c']))
        # Second part is anchored, so that the first part is ignored.
        check(['a', 'Z:b', 'c'],        ('Z:', '', ['Z:', 'b', 'c']))
        check(['a', 'Z:/b', 'c'],       ('Z:', '\\', ['Z:\\', 'b', 'c']))
        # UNC paths.
        check(['a', '//b/c', 'd'],      ('\\\\b\\c', '\\', ['\\\\b\\c\\', 'd']))
        # Collapsing and stripping excess slashes.
        check(['a', 'Z://b//c/', 'd/'], ('Z:', '\\', ['Z:\\', 'b', 'c', 'd']))
        # UNC paths.
        check(['a', '//b/c//', 'd'],    ('\\\\b\\c', '\\', ['\\\\b\\c\\', 'd']))
        # Extended paths.
        check(['//?/c:/'],              ('\\\\?\\c:', '\\', ['\\\\?\\c:\\']))
        check(['//?/c:/a'],             ('\\\\?\\c:', '\\', ['\\\\?\\c:\\', 'a']))
        check(['//?/c:/a', '/b'],       ('\\\\?\\c:', '\\', ['\\\\?\\c:\\', 'b']))
        # Extended UNC paths (format is "\\?\UNC\server\share").
        check(['//?/UNC/b/c'],          ('\\\\?\\UNC\\b\\c', '\\', ['\\\\?\\UNC\\b\\c\\']))
        check(['//?/UNC/b/c/d'],        ('\\\\?\\UNC\\b\\c', '\\', ['\\\\?\\UNC\\b\\c\\', 'd']))
        # Second part has a root but not drive.
        check(['a', '/b', 'c'],         ('', '\\', ['\\', 'b', 'c']))
        check(['Z:/a', '/b', 'c'],      ('Z:', '\\', ['Z:\\', 'b', 'c']))
        check(['//?/Z:/a', '/b', 'c'],  ('\\\\?\\Z:', '\\', ['\\\\?\\Z:\\', 'b', 'c']))
        # Joining with the same drive => the first path is appended to if
        # the second path is relative.
        check(['c:/a/b', 'c:x/y'], ('c:', '\\', ['c:\\', 'a', 'b', 'x', 'y']))
        check(['c:/a/b', 'c:/x/y'], ('c:', '\\', ['c:\\', 'x', 'y']))


#
# Tests for the pure classes.
#

class _BasePurePathTest(object):

    # Keys are canonical paths, values are list of tuples of arguments
    # supposed to produce equal paths.
    equivalences = {
        'a/b': [
            ('a', 'b'), ('a/', 'b'), ('a', 'b/'), ('a/', 'b/'),
            ('a/b/',), ('a//b',), ('a//b//',),
            # Empty components get removed.
            ('', 'a', 'b'), ('a', '', 'b'), ('a', 'b', ''),
            ],
        '/b/c/d': [
            ('a', '/b/c', 'd'), ('/a', '/b/c', 'd'),
            # Empty components get removed.
            ('/', 'b', '', 'c/d'), ('/', '', 'b/c/d'), ('', '/b/c/d'),
            ],
    }

    def setUp(self):
        p = self.cls('a')
        self.flavour = p._flavour
        self.sep = self.flavour.sep
        self.altsep = self.flavour.altsep

    def test_constructor_common(self):
        P = self.cls
        p = P('a')
        self.assertIsInstance(p, P)
        P('a', 'b', 'c')
        P('/a', 'b', 'c')
        P('a/b/c')
        P('/a/b/c')
        P(FakePath("a/b/c"))
        self.assertEqual(P(P('a')), P('a'))
        self.assertEqual(P(P('a'), 'b'), P('a/b'))
        self.assertEqual(P(P('a'), P('b')), P('a/b'))
        self.assertEqual(P(P('a'), P('b'), P('c')), P(FakePath("a/b/c")))

    def _check_str_subclass(self, *args):
        # Issue #21127: it should be possible to construct a PurePath object
        # from a str subclass instance, and it then gets converted to
        # a pure str object.
        class StrSubclass(str):
            pass
        P = self.cls
        p = P(*(StrSubclass(x) for x in args))
        self.assertEqual(p, P(*args))
        for part in p.parts:
            self.assertIs(type(part), str)

    def test_str_subclass_common(self):
        self._check_str_subclass('')
        self._check_str_subclass('.')
        self._check_str_subclass('a')
        self._check_str_subclass('a/b.txt')
        self._check_str_subclass('/a/b.txt')

    def test_join_common(self):
        P = self.cls
        p = P('a/b')
        pp = p.joinpath('c')
        self.assertEqual(pp, P('a/b/c'))
        self.assertIs(type(pp), type(p))
