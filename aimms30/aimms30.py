''' Over-the-wire serial communications format for the AIMMS-30

Internal API for static packet header:
    @classmethod header.generate(data) creates a parsed object in a 
        single pass using the total over-the-wire packet data given.

Internal API for other packet components:
    comp.__init__(header) takes a parsed _PacketHeader and constructs a 
        packet map.
    comp.parse(data) takes the total over-the-wire packet and extracts
        its components, reading them in as values as appropriate.
        
        
Note: they're using the header to detect packet frames. In theory,
    + start
    + id
    + complement
should be enough to convince me that you have the beginning of a frame.
I think the approach should be,
    1. Get a bunch of sample data
    2. Save raw data to file using pyserial
    3. Start doing python manipulation of data to figure out what the
        hell is going on
    4. Code more
    
Frame alignment can be found by just try:ing it. If parsing raises
RuntimeErrors, the frame is misaligned; move up to the next byte and try
again. Repeat until aligned. Could do a byte deque?
'''
import collections
import struct
from .utils import SliceDeque
from .utils import ParsingError
from .utils import PacketSizeError
from .utils import ChecksumMismatch


__all__ = ['Packet']


def _deque_collapse(data):
    ''' Collapses a deque into a buffer-supporting object and 
    calls super().unpack on that..
    '''
    out = bytearray()
    for digit in data:
        out.extend(digit)
    return out
    
    
def _deque_expand(obj):
    ''' Collapses a deque into a buffer-supporting object.
    '''
    out = SliceDeque()
    for digit in obj:
        out.append(digit)
    return out


def _make_deque_safe(parser):
    ''' Makes a buffer-interface packer support deques.
    '''
    class _Safed():
        def __init__(self):
            # Memoize stuff into lambdas.
            self.pack = lambda value, parser=parser: \
                _deque_expand(parser.pack(value))
            self.unpack = lambda data, parser=parser: \
                parser.unpack(_deque_collapse(data))
            
    return _Safed()
    
    
# Declare all of the structures to use
_INT8_UN = struct.Struct('<B')
_INT8_S = struct.Struct('<b')
_INT16_UN = struct.Struct('<H')
_INT16_S = struct.Struct('<h')
_FLOAT32 = struct.Struct('<f')
INT8_UN = _make_deque_safe(_INT8_UN)
INT8_S = _make_deque_safe(_INT8_S)
INT16_UN = _make_deque_safe(_INT16_UN)
INT16_S = _make_deque_safe(_INT16_S)
FLOAT32 = _make_deque_safe(_FLOAT32)


def _rescale(parser, scale):
    ''' Generator for memoized parsers that rescale.
    '''
    class _Rescaled():
        def __init__(self):
            # Memoize stuff into lambdas.
            self.pack = lambda value, scale=scale, parser=parser: \
                parser.pack(value * scale)
            self.unpack = lambda data, scale=scale, parser=parser: \
                [parser.unpack(data)[0] * scale]
                
    return _Rescaled()


class NOPARSE():
    ''' Class to mimic struct.Struct while *not* parsing any data.
    Simply returns the data as-is. Hope it's a bytes object!
    '''
    @staticmethod
    def pack(*data):
        packed = b''
        for datum in data:
            packed += datum
        return packed
    
    @staticmethod
    def unpack(data):
        return [data]
        
        
class STATUS_PARSER():
    ''' Class to unpack status flags.
    '''
    # Calculate the masks.
    MASK_WIND = 1
    MASK_PURGE = 1 << 1
    MASK_GPS = 1 << 2
    
    @classmethod
    def pack(cls, flags):
        prepacked = 0
        try:
            # If the wind key in flags is set, reflect its truth state as 
            # whether or not to raise a flag.
            if 'wind' in flags and flags['wind']:
                prepacked |= cls.MASK_WIND
            if 'purge' in flags and flags['purge']:
                prepacked |= cls.MASK_PURGE
            if 'gps' in flags and flags['gps']:
                prepacked |= cls.MASK_GPS
        except (KeyError, TypeError):
            raise TypeError('Status flags must be declared in a dict-like '
                            'construct with "wind", "purge", and "gps" keys.')
        # Now, return a packed version of that
        return INT8_UN.pack(prepacked)
        
    @classmethod
    def unpack(cls, data):
        # Initialize with all false
        result = {'wind': False, 'purge': False, 'gps': False}
        # Turn it into an integer
        unpacked = INT8_UN.unpack(data)[0]
        # Now apply the masks
        if cls.MASK_WIND & unpacked:
            result['wind'] = True
        if cls.MASK_PURGE & unpacked:
            result['purge'] = True
        if cls.MASK_GPS & unpacked:
            result['gps'] = True
        # Finally, return
        return [result]


class _PacketHeader():
    ''' Generator class for packet header parsing.
    '''
    # Build the packet map from the aimms30 operations manual
    _map = collections.OrderedDict()
    _map['start'] = slice(0, 1)
    _map['id'] = slice(1, 2)
    _map['id_complement'] = slice(2, 3)
    _map['body_length'] = slice(3, 4)
    
    # Init with a state control
    def __init__(self):
        self.data = None
        
    # Be able to return a length for the header
    @staticmethod
    def __len__(*args, **kwargs):
        return 4
    
    # Converts each part of the passed ordereddict into something useful and
    # returns a new ordereddict thereof.
    @classmethod
    def _process(cls, raw):
        # start: always " = 1 " -- ASCII, binary, ... ?
        # id: "zero for standard met. packet, 1 for aircraft state"
        # id_complement: "Bitwise complement of ID (255, 254 respectively) used 
        #     to further validate packet frame-lock"
        # body_length: "Number of bytes in data block"
        
        # Need a copy for this shizzit. Don't want to overwrite a mutable...
        processed = collections.OrderedDict()
        for key in cls._map:
            processed[key] = INT8_UN.unpack(raw[key])[0]
        
        # Do some error checking
        if processed['start'] != 1:
            raise ParsingError('Improper start of header. Misaligned frames?')
        if processed['id_complement'] != (255 - processed['id']):
            raise ParsingError('Mismatched ID and complement. Misaligned '
                               'packet frames?')
        
        # Done
        return processed
        
    # Parsing a packet requires an existing definition
    @classmethod
    def generate(cls, data):
        # First create the object
        c = cls()
        # Create the internal data store
        raw = collections.OrderedDict()
        # Don't use a dict comprehension so order is preserved
        for key, slc in cls._map.items():
            raw[key] = data[slc]
        # Process the data into useful things and return it
        return c._process(raw)
    
        
# I should refactor these as functions. Maybe as decorators of the build func?
class _MeteorologyData():
    ''' Defines packet body components for meteorology packets.
    '''
    packet_type = 'met'
    packet_id = 0
    
    _MAP = collections.OrderedDict()
    _MAP['utc_hours'] = 0, 0
    _MAP['utc_minutes'] = 1, 1
    _MAP['utc_seconds'] = 2, 2
    _MAP['temperature'] = 3, 4
    _MAP['rh'] = 5, 6
    _MAP['pressure'] = 7, 8
    _MAP['wind_vector_north'] = 9, 10
    _MAP['wind_vector_east'] = 11, 12
    _MAP['wind_speed'] = 13, 14
    _MAP['wind_direction'] = 15, 16
    _MAP['status'] = 17, 17
    
    _PARSERS = collections.OrderedDict()
    _PARSERS['utc_hours'] = INT8_UN
    _PARSERS['utc_minutes'] = INT8_UN
    _PARSERS['utc_seconds'] = INT8_UN
    _PARSERS['temperature'] = _rescale(INT16_S, 1/100)
    _PARSERS['rh'] = _rescale(INT16_UN, 1/1000)
    _PARSERS['pressure'] = _rescale(INT16_UN, 1/.5)
    _PARSERS['wind_vector_north'] = _rescale(INT16_S, 1/100)
    _PARSERS['wind_vector_east'] = _rescale(INT16_S, 1/100)
    _PARSERS['wind_speed'] = _rescale(INT16_S, 1/100)
    _PARSERS['wind_direction'] = _rescale(INT16_UN, 1/100)
    _PARSERS['status'] = STATUS_PARSER
    
    @classmethod
    def build(cls, offset):
        built_map = collections.OrderedDict()
        built_parsers = cls._PARSERS.copy()
        # Warning: non-atomic.
        for key in cls._MAP:
            relative_ends = cls._MAP[key]
            start = relative_ends[0] + offset
            end = relative_ends[1] + 1 + offset
            built_map[key] = slice(start, end)
        return built_map, built_parsers
        
    @classmethod
    def __len__(cls):
        ''' Returns the number of bytes for the packet. Should match the
        header size. Note that this is only available after init, once
        the type has been appropriately declared.
        '''
        # Isn't necessarily the most efficient way but will get the job done
        last = max([val[1] for val in cls._MAP.values()])
        first = min([val[0] for val in cls._MAP.values()])
        return (last - first + 1)
    
        
class _PositionData():
    ''' Defines packet body components for meteorology packets.
    '''
    packet_type = 'position'
    packet_id = 1
    
    _MAP = collections.OrderedDict()
    _MAP['utc_hours'] = 0, 0
    _MAP['utc_minutes'] = 1, 1
    _MAP['utc_seconds'] = 2, 2
    _MAP['latitude'] = 3, 6
    _MAP['longitude'] = 7, 10
    _MAP['altitude'] = 11, 12
    _MAP['velocity_north'] = 13, 14
    _MAP['velocity_east'] = 15, 16
    _MAP['velocity_down'] = 17, 18
    _MAP['roll'] = 19, 20
    _MAP['pitch'] = 21, 22
    _MAP['yaw'] = 23, 24
    _MAP['airspeed'] = 25, 26
    _MAP['wind_vertical'] = 27, 28
    _MAP['sideslip'] = 29, 30
    _MAP['aoa_differential'] = 31, 32
    _MAP['sideslip_differential'] = 33, 34
    
    _PARSERS = collections.OrderedDict()
    _PARSERS['utc_hours'] = INT8_UN
    _PARSERS['utc_minutes'] = INT8_UN
    _PARSERS['utc_seconds'] = INT8_UN
    _PARSERS['latitude'] = FLOAT32
    _PARSERS['longitude'] = FLOAT32
    _PARSERS['altitude'] = INT16_S
    _PARSERS['velocity_north'] = _rescale(INT16_S, 1/100)
    _PARSERS['velocity_east'] = _rescale(INT16_S, 1/100)
    _PARSERS['velocity_down'] = _rescale(INT16_S, 1/100)
    _PARSERS['roll'] = _rescale(INT16_S, 1/100)
    _PARSERS['pitch'] = _rescale(INT16_S, 1/100)
    _PARSERS['yaw'] = _rescale(INT16_S, 1/50)
    _PARSERS['airspeed'] = _rescale(INT16_S, 1/100)
    _PARSERS['wind_vertical'] = _rescale(INT16_S, 1/100)
    _PARSERS['sideslip'] = _rescale(INT16_S, 1/100)
    _PARSERS['aoa_differential'] = _rescale(INT16_S, 1/10000)
    _PARSERS['sideslip_differential'] = _rescale(INT16_S, 1/10000)
    
    @classmethod
    def build(cls, offset):
        built_map = collections.OrderedDict()
        built_parsers = cls._PARSERS.copy()
        # Warning: non-atomic.
        for key in cls._MAP:
            relative_ends = cls._MAP[key]
            start = relative_ends[0] + offset
            end = relative_ends[1] + 1 + offset
            built_map[key] = slice(start, end)
        return built_map, built_parsers
        
    @classmethod
    def __len__(cls):
        ''' Returns the number of bytes for the packet. Should match the
        header size. Note that this is only available after init, once
        the type has been appropriately declared.
        '''
        # Isn't necessarily the most efficient way but will get the job done
        last = max([val[1] for val in cls._MAP.values()])
        first = min([val[0] for val in cls._MAP.values()])
        return (last - first + 1)
    
        
class _PurgeData():
    ''' Defines packet body components for meteorology packets.
    '''
    packet_type = 'purge'
    packet_id = 4
    
    _MAP = collections.OrderedDict()
    _MAP['flow'] = 0, 1
    
    _PARSERS = collections.OrderedDict()
    _PARSERS = INT16_S
    
    @classmethod
    def build(cls, offset):
        built_map = collections.OrderedDict()
        built_parsers = cls._PARSERS.copy()
        # Warning: non-atomic.
        for key in cls._MAP:
            relative_ends = cls._MAP[key]
            start = relative_ends[0] + offset
            end = relative_ends[1] + 1 + offset
            built_map[key] = slice(start, end)
        return built_map, built_parsers
        
    @classmethod
    def __len__(cls):
        ''' Returns the number of bytes for the packet. Should match the
        header size. Note that this is only available after init, once
        the type has been appropriately declared.
        '''
        # Isn't necessarily the most efficient way but will get the job done
        last = max([val[1] for val in cls._MAP.values()])
        first = min([val[0] for val in cls._MAP.values()])
        return (last - first + 1)
        
        
class _TemperatureData():
    ''' Defines packet body components for meteorology packets.
    '''
    packet_type = 'temp'
    packet_id = 5
    
    _MAP = collections.OrderedDict()
    _MAP['forward'] = 0, 1
    _MAP['aft'] = 2, 3
    _MAP['threshold'] = 4, 5
    
    _PARSERS = collections.OrderedDict()
    _PARSERS['forward'] = INT16_S
    _PARSERS['aft'] = INT16_S
    _PARSERS['threshold'] = INT16_S
    
    @classmethod
    def build(cls, offset):
        built_map = collections.OrderedDict()
        built_parsers = cls._PARSERS.copy()
        # Warning: non-atomic.
        for key in cls._MAP:
            relative_ends = cls._MAP[key]
            start = relative_ends[0] + offset
            end = relative_ends[1] + 1 + offset
            built_map[key] = slice(start, end)
        return built_map, built_parsers
        
    @classmethod
    def __len__(cls):
        ''' Returns the number of bytes for the packet. Should match the
        header size. Note that this is only available after init, once
        the type has been appropriately declared.
        '''
        # Isn't necessarily the most efficient way but will get the job done
        last = max([val[1] for val in cls._MAP.values()])
        first = min([val[0] for val in cls._MAP.values()])
        return (last - first + 1)


class _PacketBody():
    ''' Generator class for packet body parsing.
    '''
    # Declare all possible packet types
    FMTS = _MeteorologyData, _PositionData, _PurgeData, _TemperatureData
    
    def __init__(self, header_data):
        self._map = None
        self._parsers = None
        self._packet_type = None
        self._len = None
        
        # Check each format available
        for fmt in self.FMTS:
            # To see if there's a matching packet ID
            if header_data['id'] == fmt.packet_id:
                # In which case, assign its map and parsers to self.
                self._map, self._parsers = fmt.build(_PacketHeader.__len__())
                self._packet_type = fmt.packet_type
                self._len = len(fmt())
                
        # Now catch an undetected packet type
        if self._map == None or self._parsers == None:
            raise ValueError('Inappropriate or unsupported packet type ID.')
            
    def parse(self, data):
        ''' Takes the full, unadulterated raw data from the packet and 
        parses away the body, returning it as an ordereddict.
        '''
        parsed = collections.OrderedDict()
        parsed['_type'] = self._packet_type
        for key in self._map:
            # Use the map to retrieve the appropriate bytes
            key_bytes = data[self._map[key]]
            # And then use the parser to make it useful
            parsed[key] = self._parsers[key].unpack(key_bytes)[0]
        # Finally, return the parsed packet.
        return parsed
        
    def __len__(self):
        ''' Returns the number of bytes for the packet. Should match the
        header size. Note that this is only available after init, once
        the type has been appropriately declared.
        '''
        return self._len
    
    
class _PacketFooter():
    ''' Defines and parses the packet footer (checksum)
    
    From OM:
        5+N 16-bit unsigned checksum, least significant byte
        6+N 16-bit unsigned checksum, most significant byte
        Note: The checksum includes the leading SOH character but not 
        the two checksum bytes themselves.
        
    Okay, what exactly IS the checksum? Is this a longitudinal 
    redundancy check? BSD checksum? Fletcher's? I suppose I'd guess BSD?
    '''
    _MAP = collections.OrderedDict()
    _MAP['checksum'] = 0, 1
    
    _PARSERS = collections.OrderedDict()
    _PARSERS['checksum'] = INT16_UN
    
    def __init__(self, built_map, built_parsers):
        self._map = built_map
        self._parsers = built_parsers
    
    @classmethod
    def build(cls, offset):
        built_map = collections.OrderedDict()
        built_parsers = cls._PARSERS.copy()
        # Warning: non-atomic.
        for key in cls._MAP:
            relative_ends = cls._MAP[key]
            start = relative_ends[0] + offset
            end = relative_ends[1] + 1 + offset
            built_map[key] = slice(start, end)
        return cls(built_map, built_parsers)
            
    def parse(self, data):
        ''' Takes the full, unadulterated raw data from the packet and 
        parses away the body, returning it as an ordereddict.
        '''
        parsed = collections.OrderedDict()
        for key in self._map:
            # Use the map to retrieve the appropriate bytes
            key_bytes = data[self._map[key]]
            # And then use the parser to make it useful
            parsed[key] = self._parsers[key].unpack(key_bytes)[0]
        # Finally, return the parsed packet.
        return parsed
        
    @staticmethod
    def __len__(*args, **kwargs):
        return 2
    
    
class Packet(collections.OrderedDict):
    ''' Defines and parses an entire data packet.
    
    Can memoize packet parsers in here for performance as they are 
    encountered.
    
    If the checksum doesn't match, it will correctly 
    '''
    
    def __init__(self, data):
        ''' Generates a packet from a bytes-like object. Does not mutate
        the data, but forgets it once the packet is generated.
        
        Could probably use some memoization in the future.
        '''
        # First call super.
        super().__init__(self)
        
        # Now make sure we have enough data for a header.
        if len(data) < len(_PacketHeader()):
            raise PacketSizeError('Insufficient data length to parse header.')
        
        # Header breakout from data and parsing
        header = _PacketHeader.generate(data)
        # Body processor construction
        body_builder = _PacketBody(header)
        # Footer processor construction
        # Note the -1 needed for offset from the lengths.
        footer_offset = len(_PacketHeader()) + len(body_builder)
        footer_builder = _PacketFooter.build(footer_offset)
        
        # Okay, now let's store how big it was.
        self.byte_size = footer_offset + len(footer_builder)
        
        # Now let's make sure data is long enough
        if len(data) < self.byte_size:
            raise PacketSizeError('Insufficient data length to parse packet.')
        
        # Now let's breakout and parse the body and footer.
        body = body_builder.parse(data)
        footer = footer_builder.parse(data)
        
        # This would be a good time for checking the checksum.
        # But we aren't going to do it yet, because we don't know how.
        # Because these guys didn't tell us what kind of checksum to do.
        
        self._checksum = footer['checksum']
        self._raw = bytes(_deque_collapse(data[0:self.byte_size]))
            
        # Okay, should compare the actual checksum to the calculated one
        checksum = 0
        # The checksum is a pretty simple byte sum.
        for i in range(footer_offset):
            checksum += _INT8_UN.unpack(self._raw[i: i + 1])[0]
        # Design decision: raise here, preventing packet recovery.
        if self._checksum != checksum: raise ChecksumMismatch('Bad packet.')
        
        # Finally, bring in the body.
        self._packet_type = body.pop('_type')
        self['_type'] = self.packet_type
        self['_good_checksum'] = (self._checksum == checksum)
        
        # Inefficiently and lazily copy body into self.
        for key in body:
            self[key] = body[key]
        
    @classmethod
    def from_stream(cls, stream):
        ''' Generates a packet from a deque-like stream, mutating the 
        original object to remove the packet (only if successful).
        
        Operation is atomic-ish; stream is unmodified upon failure, but
        a lack of a return doesn't automatically indicate a lack of
        stream mutation.
        '''
        # Align the stream if it's misaligned.
        while True:
            try:
                # Construct the packet
                c = cls(stream)
                break
            except ParsingError:
                del stream[0]
            except ChecksumMismatch:
                # In this case, delete the first item in the stream so we 
                # can continue?
                # del stream[0]
                raise
                
        # If we get here, we have a successful packet. Mutate the stream.
        end_of_packet = c.byte_size
        del stream[0:end_of_packet]
        return c
    
    @property
    def packet_type(self):
        ''' Read-only property to return the parsed packet type.
        '''
        return self._packet_type