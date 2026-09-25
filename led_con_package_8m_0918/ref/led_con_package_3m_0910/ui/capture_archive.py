"""Bounded-memory capture archive; temporary storage is removed on close."""
import struct
import tempfile


_RECORD = struct.Struct('<d288s')


class _Column:
    def __init__(self, archive, index):
        self.archive = archive
        self.index = index

    def __len__(self):
        return self.archive.count

    def __iter__(self):
        for record in self.archive.records():
            yield record[self.index]


class CaptureArchive:
    def __init__(self):
        self._file = tempfile.SpooledTemporaryFile(max_size=256 * 1024, mode='w+b')
        self.count = 0
        self.timestamps = _Column(self, 0)
        self.frames = _Column(self, 1)

    def append(self, timestamp, bits):
        if len(bits) != 288:
            raise ValueError('Capture frame must have 288 bits')
        self._file.seek(0, 2)
        self._file.write(_RECORD.pack(timestamp, bits))
        self.count += 1

    def records(self):
        # Seek per block so independent column iterators cannot interfere.
        for index in range(0, self.count, 128):
            self._file.seek(index * _RECORD.size)
            block = self._file.read(min(128, self.count - index) * _RECORD.size)
            yield from _RECORD.iter_unpack(block)

    def clear(self):
        self._file.seek(0)
        self._file.truncate()
        self.count = 0

    def close(self):
        self._file.close()
