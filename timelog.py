#!/usr/bin/env python3
__author__ = 'xhaskx@gmail.com'
__source__ = 'https://github.com/xHasKx/timelog'

import re
import sys
from mmap import mmap
from shlex import quote, join
from os import execvp, SEEK_SET
from argparse import ArgumentParser, Namespace, RawDescriptionHelpFormatter, ArgumentDefaultsHelpFormatter


# log line examples:
# [tg.localhost#1] INF: 2023/04/12 21:40:39:210: [app] signal_cb: terminating by signal 15
# INF: 2023/04/12 21:40:39:210: [app#2] signal_cb: terminating by signal 15


TIME_LEN = 23
'Size of the time string in bytes, 23 is for b"2023/04/12 16:34:42:099"'

CHUNKSIZE = 20 * 4096
'Default chunk size to do a linear search. Assume that several log lines with different time will fit in the memory block of that size'

FULL_DATE_TIME_RE = re.compile(br'^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}:\d{3}$')
'Regexp matching proper full time bytes like b"2023/04/12 16:34:42:099"'

SHORT_DATE_TIME_HMS_RE = re.compile(r'^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}$')
'Regexp matching proper date and short time string in `YYYY/mm/dd HH:MM:SS` format'

SHORT_DATE_TIME_HM_RE = re.compile(r'^\d{4}/\d{2}/\d{2} \d{2}:\d{2}$')
'Regexp matching proper date and short time string in `YYYY/mm/dd HH:MM` format'

DATE_RE = re.compile(r'^\d{4}/\d{2}/\d{2}$')
'Regexp matching proper date string in YYYY/mm/dd format'

TIME_RE = re.compile(r'^\d{2}:\d{2}:\d{2}:\d{3}$')
'Regexp matching proper short time string in HH:MM:SS:sss format'

TIME_HMS_RE = re.compile(r'^\d{2}:\d{2}:\d{2}$')
'Regexp matching proper short time string in HH:MM:SS format'

TIME_HM_RE = re.compile(r'^\d{2}:\d{2}$')
'Regexp matching proper short time string in HH:MM format'

class TextFormatter(ArgumentDefaultsHelpFormatter, RawDescriptionHelpFormatter):
    '''
    ArgumentParser help, epilog and args defaults formatter
    '''

def create_argparser() -> ArgumentParser:
    '''
    Returns configured ArgumentParser instance for the script
    '''
    parser = ArgumentParser(
        formatter_class=TextFormatter,
        description= \
            'Perform a binary search for the specified time in a big text log file.\n'
            'Print found log lines to stdout by executing `dd` with proper args,\n'
            'or view it with `less` with proper position on found time.',
        epilog= \
            'Examples of the resulting commands:\n'
            '\n'
            '    dd status=none if=bigfile.log iflag=skip_bytes skip=2488818942\n'
            '    dd status=none if=bigfile.log iflag=skip_bytes,count_bytes skip=2488818942 count=451258\n'
            '    less -n +2488818942P bigfile.log'
    )
    parser.add_argument('filename',             help='Path to the log file')
    parser.add_argument('time_from',            help='Time string to search the first line in log file. '
                                                        'Can be in one of the following formats: '
                                                        '`YYYY/mm/dd HH:MM:SS:sss` (full), '
                                                        '`YYYY/mm/dd HH:MM:SS`, `YYYY/mm/dd HH:MM` (short), '
                                                        '`YY/mm/dd` (date only), '
                                                        '`HH:MM:SS:sss`, `HH:MM:SS`, or `HH:MM` (time only, date from the first line of file)')
    parser.add_argument('-l', '--less',         help='Use `less` program to view the file instead of printing it with `dd`. '
                                                        'Conflicts with --time-to option', action='store_true')
    parser.add_argument('-t', '--time-to',      help='Set the last time string to output from in log file, '
                                                        'NOT INCLUSIVE. Conflicts with --less option. '
                                                        'The same format as for time_from')
    parser.add_argument('-v', '--verbose',      help='Show debug info on stderr', action='store_true')
    parser.add_argument('-d', '--debug',        help='Debug binary search stages to stderr', action='store_true')
    parser.add_argument('-a', '--arg',          help='Add an extra argument to the resulting command line', action='append')
    parser.add_argument('-n', '--noexec',       help='Do not execute resulting command, just print it to stdout', action='store_true')
    parser.add_argument('-c', '--chunksize',    help='Max chunk size for linear search in file', default=CHUNKSIZE, type=int)
    return parser

def is_valid_time(data: bytes) -> bool:
    '''
    Returns True if given bytes is a valid time string in form b"2023/04/12 16:34:42:099"
    '''
    if len(data) != TIME_LEN:
        return False
    if not FULL_DATE_TIME_RE.match(data):
        return False
    return True

def mem_extract_time(mem: mmap, end: int) -> bytes:
    '''
    Returns a bytes with time from the current mem position, up to specified end position.
    Expecting mem position is on the first char of line.
    Returns None if time cannot be found
    '''
    start = mem.tell()
    while mem.tell() < end:
        time_begin = mem.find(b': ', start, end)
        if time_begin == -1:
            return None
        time_begin += 2
        mem.seek(time_begin, SEEK_SET)
        data = mem.read(TIME_LEN)
        if is_valid_time(data):
            return data
        start = mem.tell()
    return None

def mem_skip_line_begin_right(mem: mmap, end: int) -> int:
    '''
    Skip mem position to the first char of the next line.
    Returns position of the next line first char, or -1 if it can't be found.
    '''
    start = mem.tell()
    line_end = mem.find(b'\n', start, end)
    if line_end == -1:
        return -1
    line_begin = line_end + 1
    if line_begin >= end:
        return -1
    mem.seek(line_begin, SEEK_SET)
    return line_begin

def mem_skip_line_begin_left(mem: mmap, start: int) -> int:
    '''
    Skip mem position to the first char of the current line.
    Returns position of the current line first char, or -1 if it can't be found
    '''
    end = mem.tell()
    # assuming line should contain TIME_LEN bytes at least
    begin = end - TIME_LEN
    if begin < start:
        return -1
    line_end = mem.rfind(b'\n', start, begin)
    if line_end == -1:
        return -1
    line_begin = line_end + 1
    mem.seek(line_begin, SEEK_SET)
    return line_begin

def stderr(*rest):
    'Print-like function writing to stderr'
    print(*rest, file=sys.stderr)

def debug(args: Namespace, *rest):
    'Print-like function writing to stderr if verbosity is enabled in args'
    if args.verbose:
        stderr('#', *rest)

def debug_binsearch(args: Namespace, *rest):
    'Print-like function writing to stderr if debug is enabled in args'
    if args.debug:
        stderr('#', *rest)

def binary_search(args: Namespace, chunksize: int, mem: mmap, time: bytes, m_begin: int, m_size: int) -> tuple[bool, int]:
    '''
    Do a binary search in the specified block of the memory mapped file.
    Expecting m_begin to be the offset of the first line char, and m_begin+m_size points to the next line first char after the block end.
    For m_size <= chunksize perform a simple linear search and return offset of the first or last time.
    On success returns a tuple (True, <pos>) where <pos> is the position after the matching time.
    On failure returns a tuple (False, -1) or (False, 1), if time should be found in the previous or next time space.
    Raises RuntimeError on unrecoverable failures.
    '''

    if m_size <= chunksize:
        # finally do a plain search in a relatively small area of chunksize
        # advancing search begin position to the half of chunk to avoid skipping some lines with the same matching time
        m_begin -= chunksize // 2
        end = m_begin + m_size + chunksize // 2
        mem.seek(m_begin, SEEK_SET)
        while mem.tell() < end:
            current_time = mem_extract_time(mem, end)
            pos = mem.tell()
            debug_binsearch(args, "--- linear search:", time, pos, current_time)
            if current_time >= time:
                return (True, pos)
            next_line = mem_skip_line_begin_right(mem, end)
            if next_line == -1:
                raise RuntimeError('failed to advance to next_line')
        raise RuntimeError('linear search failed, try to enlarge chunksize')

    # searching in the first line of the left chunk
    left_chunk_start = m_begin
    left_chunk_end = left_chunk_start + chunksize
    left_time = mem_extract_time(mem, left_chunk_end)
    debug_binsearch(args, "--- binary search:", time, m_begin, m_size, "left_time:", left_time)
    if not left_time:
        raise RuntimeError('failed to extract left_time')
    if time < left_time:
        return (False, -1)
    if time == left_time:
        return (True, mem.tell() - TIME_LEN)
    after_left_line = mem_skip_line_begin_right(mem, left_chunk_end)
    if after_left_line == -1:
        raise RuntimeError('failed to advace to the after_left_line')

    # searching in the last line of the right chunk
    right_chunk_end = m_begin + m_size
    right_chunk_start = right_chunk_end - chunksize
    mem.seek(right_chunk_end, SEEK_SET)
    while mem.tell() > right_chunk_start:
        pos = mem.tell()
        right_line = mem_skip_line_begin_left(mem, right_chunk_start)
        if right_line == -1:
            raise RuntimeError('failed to advance to the right_line')
        right_time = mem_extract_time(mem, right_chunk_end)
        if not right_time:
            mem.seek(pos - 1, SEEK_SET)
        else:
            break
    debug_binsearch(args, "--- binary search:", time, m_begin, m_size, "right_time:", right_time)
    if not right_time:
        raise RuntimeError('failed to extract right_time')
    if time > right_time:
        return (False, 1)
    if time == right_time:
        return (True, mem.tell() - TIME_LEN)
    before_right_line = right_line - 1

    # now search in the middle
    middle_size = before_right_line - after_left_line
    middle_pos = after_left_line + middle_size // 2
    middle_chunk_start = middle_pos - chunksize // 2
    middle_chunk_end = middle_chunk_start + chunksize
    mem.seek(middle_pos, SEEK_SET)
    middle_line = mem_skip_line_begin_left(mem, middle_chunk_start)
    mem.seek(middle_line, SEEK_SET)
    middle_time = mem_extract_time(mem, middle_chunk_end)
    debug_binsearch(args, "--- binary search:", time, m_begin, m_size, "middle_time:", middle_time)

    if time == middle_time:
        return (True, mem.tell() - TIME_LEN)
    if time < middle_time:
        # continue search in the left half, from after_left_line up to middle_line
        mem.seek(after_left_line, SEEK_SET)
        return binary_search(args, chunksize, mem, time, after_left_line, middle_line - after_left_line)
    elif time > middle_time:
        # continue search in the right half
        # skip to the next line
        after_middle_line = mem_skip_line_begin_right(mem, middle_chunk_end)
        if after_middle_line == -1:
            raise RuntimeError('failed to advance to after_middle_line')
        mem.seek(after_middle_line, SEEK_SET)
        return binary_search(args, chunksize, mem, time, after_middle_line, right_line - after_middle_line)

class LogicError(Exception):
    'Exception class for logic errors'
    pass

def do_binary_search(chunksize: int, title: str, args: Namespace, mem: mmap, time: bytes, size: int) -> int:
    '''
    Perform a binary search and return the line position with found time
    '''
    found, pos = binary_search(args, chunksize, mem, time, 0, size)
    debug(args, title, found, pos)
    if not found:
        if pos < 0:
            raise LogicError('log file starts from lines with fresher time than ' + time.decode())
        if pos > 0:
            raise LogicError('log file ends with lines with older time than ' + time.decode())
        raise RuntimeError('unexpected pos: ' + str(pos))
    # advance pos to the line beginning
    mem.seek(pos, SEEK_SET)
    line_begin = mem_skip_line_begin_left(mem, pos - chunksize)
    if line_begin == -1:
        if pos > chunksize:
            raise RuntimeError('failed to advance to line_begin')
        line_begin = 0
    return line_begin

def fix_time(mem: mmap, args: Namespace, time: str, prev_time: str) -> str:
    '''
    Returns full time string from possible partial time
    '''
    if not time:
        return None
    if not is_valid_time(time.encode()):
        fixed_time = None
        if SHORT_DATE_TIME_HMS_RE.match(time):
            fixed_time = time + ':000'
        if SHORT_DATE_TIME_HM_RE.match(time):
            fixed_time = time + ':00:000'
        elif DATE_RE.match(time):
            fixed_time = time + ' 00:00:00:000'
        if fixed_time:
            debug(args, 'Fixed time', time, '==>', fixed_time)
        else:
            # no date, so use it from the previous time or from first line in the file
            if not prev_time:
                prev_time = mem_extract_time(mem, args.chunksize)
                prev_time = prev_time.decode()
            date = prev_time[:11] # for "YYYY/mm/dd "
            if TIME_RE.match(time):
                fixed_time = date + time
            elif TIME_HMS_RE.match(time):
                fixed_time = date + time + ':000'
            elif TIME_HM_RE.match(time):
                fixed_time = date + time + ':00:000'
            else:
                raise LogicError('failed to fix time `' + time + '` to a valid time string')
            debug(args, 'Fixed time', time, 'using date of', prev_time, '==>', fixed_time)
        if not is_valid_time(fixed_time.encode()):
            raise LogicError('failed to fix time `' + time + '` to a valid time string, result is ' + fixed_time)
        return fixed_time
    else:
        return time

def main():
    '''
    Perform the script actions
    '''
    args = create_argparser().parse_args()
    debug(args, 'Args:', args)

    try:
        # open and mmap file
        with open(args.filename, 'r+b') as f:
            mem = mmap(f.fileno(), 0)
            size = mem.size()

            # preprocess args
            time_from = fix_time(mem, args, args.time_from, None)
            time_to = fix_time(mem, args, args.time_to, time_from)

            # check args
            if time_to and time_to < time_from:
                raise LogicError('expecting `--time-to <time_to>` to be >= `<time_from>`')
            if time_to and args.less:
                raise LogicError('--time-to and --less conflicts')

            # search the first time in log
            mem.seek(0, SEEK_SET)
            line_begin = do_binary_search(args.chunksize, 'First binary search:', args, mem, time_from.encode(), size)

            # make command
            if args.less:
                command = ['less',
                           '-n', # to disable lines calculation
                           '+' + str(line_begin) + 'P',
                           quote(args.filename)]
            else:
                command = ['dd',
                           'status=none',
                           'if=' + quote(args.filename),]
                if time_to:
                    # search the to-time in log
                    mem.seek(0, SEEK_SET)
                    to_line_begin = do_binary_search(args.chunksize, 'To-time binary search:', args, mem, time_to.encode(), size)
                    command += ['iflag=skip_bytes,count_bytes']
                else:
                    command += ['iflag=skip_bytes']
                command += ['skip=' + str(line_begin)]
                if time_to:
                    command += ['count=' + str(to_line_begin - line_begin)]
            if args.arg:
                command += args.arg
            debug(args, 'Command:', join(command))

            # maybe print command
            if args.noexec:
                print(join(command))
                sys.exit()

            # flush stderr with possible debug info
            sys.stderr.flush()

            # and finally execute command with exec(), replacing current process
            execvp(command[0], command)

    except LogicError as e:
        stderr('Error:', str(e))
        sys.exit(1)


if __name__ == '__main__':
    main()
