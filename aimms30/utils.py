import threading
import collections
import itertools
import time


class ParsingError(RuntimeError):
    ''' Very likely to indicate misaligned packet frames.
    '''
    pass
    
    
class PacketSizeError(RuntimeError):
    ''' Presumably, this means the packet is too small.
    '''
    pass
    
    
class ChecksumMismatch(RuntimeError):
    pass
    
    
class MinimumLoopDelay():
    ''' Ensures a minimum amount of time has passed within a loop, to
    minimize CPU hogging of repeated operations. The loop should always
    last longer than must_exceed seconds. '''
    def __init__(self, must_exceed):
        if not must_exceed:
            self.limit = 0
        else:
            self.limit = must_exceed
        
    def __enter__(self):
        self.start = time.monotonic()
        
    def __exit__(self, exception_type, exception_value, traceback):
        duration = time.monotonic() - self.start
        do_delay = self.limit - duration
        if do_delay > 0:
            time.sleep(do_delay)
            

class SliceDeque(collections.deque):
    ''' Deque that implements slicing in gets, deletes.
    '''
    def __init__(self, *args, **kwargs):
        ''' Add in a lock for self.
        '''
        super().__init__(*args, **kwargs)
        self._lock = threading.Lock()
        
    def __getitem__(self, index):
        ''' Implements slicing for getting.
        '''
        with self._lock:
            if isinstance(index, slice):
                return type(self)(itertools.islice(self, index.start,
                                                   index.stop, index.step))
            return collections.deque.__getitem__(self, index)
        
    def __setitem__(self, index, value):
        ''' Implements slicing for setting.
        '''
        with self._lock:
            if isinstance(index, slice):
                start = index.start
                stop = index.stop
                step = index.step or 1
                
                backup = []
                
                # Error trap the respective sizes
                if len(range(start, stop, step)) != len(value):
                    raise ValueError('Slice must be same length as values.')
                     
                # Try/catch for too large of a slice and atomic changes.
                try:
                    for i in range(start, stop, step):
                        backup.append(super().__getitem__(i))
                        super().__setitem__(i, value.pop(0))
                except IndexError:
                    # Restore the values!
                    try:
                        for i in range(start, stop, step):
                            super().__setitem__(i, backup.pop(0))
                    except IndexError:
                        pass
                    # And re-raise the error.
                    raise IndexError('Index out of range.')
            else:
                super().__setitem__(index, value)
        
    def __delitem__(self, index):
        ''' Implements slicing for deletes.
        '''
        with self._lock:
            if isinstance(index, slice):
                start = index.start
                stop = index.stop
                step = index.step or 1
                
                backup = []
                offset = 0
                     
                # Try/catch for too large of a slice and atomic changes.
                try:
                    for i in range(start, stop, step):
                        # Pop it and add it to the backup.
                        backup.append(self._poppat(i + offset))
                        offset -= 1
                except Exception as e:
                    # Restore the values! Note that this will automatically
                    # re-raise an indexerror when the reset index goes out
                    # of range.
                    try:
                        for i in range(start, stop, step):
                            # Note that no offset is needed here, as the deque
                            # will be built back out as it goes.
                            self._insert(i, backup.pop(0))
                    except IndexError:
                        pass
                    # Reraise.
                    raise e
            else:
                super().__delitem__(index)
        
    def __iadd__(self, *args, **kwargs):
        self.extend(*args, **kwargs)
        
    def append(self, *args, **kwargs):
        with self._lock:
            super().append(*args, **kwargs)
        
    def appendleft(self, *args, **kwargs):
        with self._lock:
            super().appendleft(*args, **kwargs)
        
    def clear(self, *args, **kwargs):
        with self._lock:
            super().clear(*args, **kwargs)
        
    def extend(self, *args, **kwargs):
        with self._lock:
            super().extend(*args, **kwargs)
        
    def extendleft(self, *args, **kwargs):
        with self._lock:
            super().extendleft(*args, **kwargs)
        
    def pop(self, *args, **kwargs):
        with self._lock:
            return super().pop(*args, **kwargs)
        
    def popleft(self, *args, **kwargs):
        with self._lock:
            return super().popleft(*args, **kwargs)
        
    def remove(self, *args, **kwargs):
        with self._lock:
            super().remove(*args, **kwargs)
        
    def reverse(self, *args, **kwargs):
        with self._lock:
            return super().reverse(*args, **kwargs)
        
    def rotate(self, *args, **kwargs):
        with self._lock:
            super().rotate(*args, **kwargs)
            
    def _insert(self, index, value):
        ''' Used explicitly for deleting. Does not lock, because that 
        would block (unless self._lock were reentrant). IS NOT PUBLIC;
        IS NOT THREADSAFE unless used within another blocking function.
        '''
        # Have to directly call super method, or we'll block.
        super().rotate(-index)
        super().appendleft(value)
        super().rotate(index)
            
    def _poppat(self, index):
        ''' Used explicitly for deleting. Does not lock, because that 
        would block (unless self._lock were reentrant). IS NOT PUBLIC;
        IS NOT THREADSAFE unless used within another blocking function.
        '''
        # Get the value. Don't use rotate and pop because then we need to
        # deal with indices that are larger than the deque and etc etc etc
        value = super().__getitem__(index)
        super().__delitem__(index)
        return value