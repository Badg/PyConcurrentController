import threading
import collections
import itertools
import time
import http.server
import tempfile
import urllib
import posixpath
import mimetypes
import json
from http.server import HTTPServer
from socketserver import ThreadingMixIn
import os
import shutil


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
      
      
class ThreadedStatefulSocketServer(ThreadingMixIn, HTTPServer):
    allow_reuse_address = True
    
    def __init__(self, state_vector, *args, **kwargs):
        self.state_vector = state_vector
        super().__init__(*args, **kwargs)
    
    def shutdown(self):
        self.socket.close()
        super().shutdown()
        

class RestfulDictHandler(http.server.BaseHTTPRequestHandler):
    """Simple HTTP request handler with GET and HEAD commands.

    This serves files from the current directory and any of its
    subdirectories.  The MIME type for files is determined by
    calling the .guess_type() method.

    The GET and HEAD requests are identical except that the HEAD
    request omits the actual contents of the file.

    """

    __version__ = '0.0.1'
    server_version = "RestfulDictHandler/" + __version__

    def do_GET(self):
        """Serve a GET request. MUST BE WRAPPED by parent to eliminate
        state."""
        f = self.send_head()
        if f:
            try:
                self.copyfile(f, self.wfile)
            finally:
                f.close()

    def do_HEAD(self):
        """Serve a HEAD request."""
        f = self.send_head()
        if f:
            f.close()
            
    def do_POST(self):
        ''' Serve a POST request.
        '''
        content = self.rfile

    def send_head(self):
        """Common code for GET and HEAD commands.

        This sends the response code and MIME headers.

        Return value is either a file object (which has to be copied
        to the outputfile by the caller unless the command was HEAD,
        and must be closed by the caller under all circumstances), or
        None, in which case the caller has nothing further to do.

        """
        # Hardcode path handling for RESTfulness.
        # Don't forget to strip the original '/' to avoid having an empty
        # string at the beginning of the path string. Could do this other ways
        # as well, this is a bit ungraceful
        restful = self.path.strip('/').split('/')
        try:
            _state = self.server.state_vector
            for key in restful:
                # Check to make sure there was a string
                if key:
                    # Mutate _state until we divide it into the desired key
                    _state = _state[key]
                else:
                    break
        except KeyError:
            self.send_response(404)
            return None
        
        output_string = json.dumps(_state)
        
        # Open a temporary file for piping.
        f = tempfile.TemporaryFile()
        # Write the _state to f
        f.write(output_string.encode())
        # THIS IS REALLY IMPORTANT.
        # Otherwise will return blank.
        f.seek(0)
        
        # Begin the response sequence.
        self.send_response(200)
        ctype = 'text/plain'
        self.send_header("Content-type", ctype)
        fs = os.fstat(f.fileno())
        self.send_header("Content-Length", str(fs[6]))
        self.send_header("Last-Modified", 
            self.date_time_string(fs.st_mtime))
        self.end_headers()
        
        # Return the file-like object, to maintain compatibility with do_GET
        return f
        
        
    def _dont_send_head(self):
        """Common code for GET and HEAD commands.

        This sends the response code and MIME headers.

        Return value is either a file object (which has to be copied
        to the outputfile by the caller unless the command was HEAD,
        and must be closed by the caller under all circumstances), or
        None, in which case the caller has nothing further to do.

        """
        path = self.translate_path(self.path)
        f = None
        if os.path.isdir(path):
            parts = urllib.parse.urlsplit(self.path)
            if not parts.path.endswith('/'):
                # redirect browser - doing basically what apache does
                self.send_response(301)
                new_parts = (parts[0], parts[1], parts[2] + '/',
                             parts[3], parts[4])
                new_url = urllib.parse.urlunsplit(new_parts)
                self.send_header("Location", new_url)
                self.end_headers()
                return None
            for index in "index.html", "index.htm":
                index = os.path.join(path, index)
                if os.path.exists(index):
                    path = index
                    break
            else:
                return self.list_directory(path)
        ctype = self.guess_type(path)
        try:
            f = open(path, 'rb')
        except OSError:
            self.send_error(404, "File not found")
            return None
        try:
            self.send_response(200)
            self.send_header("Content-type", ctype)
            fs = os.fstat(f.fileno())
            self.send_header("Content-Length", str(fs[6]))
            self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
            self.end_headers()
            return f
        except:
            f.close()
            raise

    def list_directory(self, path):
        """Helper to produce a directory listing (absent index.html).

        Return value is either a file object, or None (indicating an
        error).  In either case, the headers are sent, making the
        interface the same as for send_head().

        """
        try:
            list = os.listdir(path)
        except OSError:
            self.send_error(404, "No permission to list directory")
            return None
        list.sort(key=lambda a: a.lower())
        r = []
        try:
            displaypath = urllib.parse.unquote(self.path,
                                               errors='surrogatepass')
        except UnicodeDecodeError:
            displaypath = urllib.parse.unquote(path)
        displaypath = html.escape(displaypath)
        enc = sys.getfilesystemencoding()
        title = 'Directory listing for %s' % displaypath
        r.append('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN" '
                 '"http://www.w3.org/TR/html4/strict.dtd">')
        r.append('<html>\n<head>')
        r.append('<meta http-equiv="Content-Type" '
                 'content="text/html; charset=%s">' % enc)
        r.append('<title>%s</title>\n</head>' % title)
        r.append('<body>\n<h1>%s</h1>' % title)
        r.append('<hr>\n<ul>')
        for name in list:
            fullname = os.path.join(path, name)
            displayname = linkname = name
            # Append / for directories or @ for symbolic links
            if os.path.isdir(fullname):
                displayname = name + "/"
                linkname = name + "/"
            if os.path.islink(fullname):
                displayname = name + "@"
                # Note: a link to a directory displays with @ and links with /
            r.append('<li><a href="%s">%s</a></li>'
                    % (urllib.parse.quote(linkname,
                                          errors='surrogatepass'),
                       html.escape(displayname)))
        r.append('</ul>\n<hr>\n</body>\n</html>\n')
        encoded = '\n'.join(r).encode(enc, 'surrogateescape')
        f = io.BytesIO()
        f.write(encoded)
        f.seek(0)
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=%s" % enc)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        return f

    def translate_path(self, path):
        """Translate a /-separated PATH to the local filename syntax.

        Components that mean special things to the local file system
        (e.g. drive or directory names) are ignored.  (XXX They should
        probably be diagnosed.)

        """
        # abandon query parameters
        path = path.split('?',1)[0]
        path = path.split('#',1)[0]
        # Don't forget explicit trailing slash when normalizing. Issue17324
        trailing_slash = path.rstrip().endswith('/')
        try:
            path = urllib.parse.unquote(path, errors='surrogatepass')
        except UnicodeDecodeError:
            path = urllib.parse.unquote(path)
        path = posixpath.normpath(path)
        words = path.split('/')
        words = filter(None, words)
        path = os.getcwd()
        for word in words:
            drive, word = os.path.splitdrive(word)
            head, word = os.path.split(word)
            if word in (os.curdir, os.pardir): continue
            path = os.path.join(path, word)
        if trailing_slash:
            path += '/'
        return path

    def copyfile(self, source, outputfile):
        """Copy all data between two file objects.

        The SOURCE argument is a file object open for reading
        (or anything with a read() method) and the DESTINATION
        argument is a file object open for writing (or
        anything with a write() method).

        The only reason for overriding this would be to change
        the block size or perhaps to replace newlines by CRLF
        -- note however that this the default server uses this
        to copy binary data as well.

        """
        shutil.copyfileobj(source, outputfile)

    def guess_type(self, path):
        """Guess the type of a file.

        Argument is a PATH (a filename).

        Return value is a string of the form type/subtype,
        usable for a MIME Content-type header.

        The default implementation looks the file's extension
        up in the table self.extensions_map, using application/octet-stream
        as a default; however it would be permissible (if
        slow) to look inside the data to make a better guess.

        """

        base, ext = posixpath.splitext(path)
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        ext = ext.lower()
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        else:
            return self.extensions_map['']

    if not mimetypes.inited:
        mimetypes.init() # try to read system mime.types
    extensions_map = mimetypes.types_map.copy()
    extensions_map.update({
        '': 'application/octet-stream', # Default
        '.py': 'text/plain',
        '.c': 'text/plain',
        '.h': 'text/plain',
        })
    

class QuietRestfulDictHandler(RestfulDictHandler):
    def log_message(self, *args, **kwargs):
        return

    
class TestHandler(http.server.BaseHTTPRequestHandler):
    """Simple HTTP request handler with GET and HEAD commands.

    This serves files from the current directory and any of its
    subdirectories.  The MIME type for files is determined by
    calling the .guess_type() method.

    The GET and HEAD requests are identical except that the HEAD
    request omits the actual contents of the file.

    """

    server_version = "TestServer/0.0.1"

    def do_GET(self):
        """Serve a GET request."""
        f = self.send_head()
        if f:
            try:
                self.copyfile(f, self.wfile)
            finally:
                f.close()

    def do_HEAD(self):
        """Serve a HEAD request."""
        f = self.send_head()
        if f:
            f.close()
            
    def do_POST(self):
        ''' Serve a POST request.
        '''
        content = self.rfile

    def send_head(self):
        """Common code for GET and HEAD commands.

        This sends the response code and MIME headers.

        Return value is either a file object (which has to be copied
        to the outputfile by the caller unless the command was HEAD,
        and must be closed by the caller under all circumstances), or
        None, in which case the caller has nothing further to do.

        """
        # Hardcode path handling for RESTfulness.
        restful = self.path.split('/')
        device = restful[1]
        
        # Open a temporary file for piping.
        f = tempfile.TemporaryFile()
        # Write an encoded version of the device (For testing!) to f
        f.write(device.encode())
        # THIS IS REALLY IMPORTANT.
        # Otherwise will return blank.
        f.seek(0)
        
        # Begin the response sequence.
        self.send_response(200)
        ctype = 'text/plain'
        self.send_header("Content-type", ctype)
        fs = os.fstat(f.fileno())
        self.send_header("Content-Length", str(fs[6]))
        self.send_header("Last-Modified", 
            self.date_time_string(fs.st_mtime))
        self.end_headers()
        
        # Return the file-like object, to maintain compatibility with do_GET
        return f
        
        
    def _dont_send_head(self):
        """Common code for GET and HEAD commands.

        This sends the response code and MIME headers.

        Return value is either a file object (which has to be copied
        to the outputfile by the caller unless the command was HEAD,
        and must be closed by the caller under all circumstances), or
        None, in which case the caller has nothing further to do.

        """
        path = self.translate_path(self.path)
        f = None
        if os.path.isdir(path):
            parts = urllib.parse.urlsplit(self.path)
            if not parts.path.endswith('/'):
                # redirect browser - doing basically what apache does
                self.send_response(301)
                new_parts = (parts[0], parts[1], parts[2] + '/',
                             parts[3], parts[4])
                new_url = urllib.parse.urlunsplit(new_parts)
                self.send_header("Location", new_url)
                self.end_headers()
                return None
            for index in "index.html", "index.htm":
                index = os.path.join(path, index)
                if os.path.exists(index):
                    path = index
                    break
            else:
                return self.list_directory(path)
        ctype = self.guess_type(path)
        try:
            f = open(path, 'rb')
        except OSError:
            self.send_error(404, "File not found")
            return None
        try:
            self.send_response(200)
            self.send_header("Content-type", ctype)
            fs = os.fstat(f.fileno())
            self.send_header("Content-Length", str(fs[6]))
            self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
            self.end_headers()
            return f
        except:
            f.close()
            raise

    def list_directory(self, path):
        """Helper to produce a directory listing (absent index.html).

        Return value is either a file object, or None (indicating an
        error).  In either case, the headers are sent, making the
        interface the same as for send_head().

        """
        try:
            list = os.listdir(path)
        except OSError:
            self.send_error(404, "No permission to list directory")
            return None
        list.sort(key=lambda a: a.lower())
        r = []
        try:
            displaypath = urllib.parse.unquote(self.path,
                                               errors='surrogatepass')
        except UnicodeDecodeError:
            displaypath = urllib.parse.unquote(path)
        displaypath = html.escape(displaypath)
        enc = sys.getfilesystemencoding()
        title = 'Directory listing for %s' % displaypath
        r.append('<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN" '
                 '"http://www.w3.org/TR/html4/strict.dtd">')
        r.append('<html>\n<head>')
        r.append('<meta http-equiv="Content-Type" '
                 'content="text/html; charset=%s">' % enc)
        r.append('<title>%s</title>\n</head>' % title)
        r.append('<body>\n<h1>%s</h1>' % title)
        r.append('<hr>\n<ul>')
        for name in list:
            fullname = os.path.join(path, name)
            displayname = linkname = name
            # Append / for directories or @ for symbolic links
            if os.path.isdir(fullname):
                displayname = name + "/"
                linkname = name + "/"
            if os.path.islink(fullname):
                displayname = name + "@"
                # Note: a link to a directory displays with @ and links with /
            r.append('<li><a href="%s">%s</a></li>'
                    % (urllib.parse.quote(linkname,
                                          errors='surrogatepass'),
                       html.escape(displayname)))
        r.append('</ul>\n<hr>\n</body>\n</html>\n')
        encoded = '\n'.join(r).encode(enc, 'surrogateescape')
        f = io.BytesIO()
        f.write(encoded)
        f.seek(0)
        self.send_response(200)
        self.send_header("Content-type", "text/html; charset=%s" % enc)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        return f

    def translate_path(self, path):
        """Translate a /-separated PATH to the local filename syntax.

        Components that mean special things to the local file system
        (e.g. drive or directory names) are ignored.  (XXX They should
        probably be diagnosed.)

        """
        # abandon query parameters
        path = path.split('?',1)[0]
        path = path.split('#',1)[0]
        # Don't forget explicit trailing slash when normalizing. Issue17324
        trailing_slash = path.rstrip().endswith('/')
        try:
            path = urllib.parse.unquote(path, errors='surrogatepass')
        except UnicodeDecodeError:
            path = urllib.parse.unquote(path)
        path = posixpath.normpath(path)
        words = path.split('/')
        words = filter(None, words)
        path = os.getcwd()
        for word in words:
            drive, word = os.path.splitdrive(word)
            head, word = os.path.split(word)
            if word in (os.curdir, os.pardir): continue
            path = os.path.join(path, word)
        if trailing_slash:
            path += '/'
        return path

    def copyfile(self, source, outputfile):
        """Copy all data between two file objects.

        The SOURCE argument is a file object open for reading
        (or anything with a read() method) and the DESTINATION
        argument is a file object open for writing (or
        anything with a write() method).

        The only reason for overriding this would be to change
        the block size or perhaps to replace newlines by CRLF
        -- note however that this the default server uses this
        to copy binary data as well.

        """
        shutil.copyfileobj(source, outputfile)

    def guess_type(self, path):
        """Guess the type of a file.

        Argument is a PATH (a filename).

        Return value is a string of the form type/subtype,
        usable for a MIME Content-type header.

        The default implementation looks the file's extension
        up in the table self.extensions_map, using application/octet-stream
        as a default; however it would be permissible (if
        slow) to look inside the data to make a better guess.

        """

        base, ext = posixpath.splitext(path)
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        ext = ext.lower()
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        else:
            return self.extensions_map['']

    if not mimetypes.inited:
        mimetypes.init() # try to read system mime.types
    extensions_map = mimetypes.types_map.copy()
    extensions_map.update({
        '': 'application/octet-stream', # Default
        '.py': 'text/plain',
        '.c': 'text/plain',
        '.h': 'text/plain',
        })