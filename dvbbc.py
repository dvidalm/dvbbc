#!/usb/bin/env python
# dvbbc.py - Stream live TV over HTTP to multiple viewers
# Copyright (C) 2013  Mansour Behabadi <mansour@oxplot.com>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at
# your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

from socketserver import ThreadingMixIn
from subprocess import Popen, PIPE
from urllib.parse import quote as urlenc, unquote as urldec
from wsgiref.simple_server import make_server, WSGIServer
from wsgiref.validate import validator
from xml.sax.saxutils import escape
import os,sys,threading,time,argparse

HTMLENC = {'"': '&quot;', "'": '&apos'}
htmlenc = lambda c: escape(c, HTMLENC)
CHANS_TPL = """<!DOCTYPE html><html><body><h1>Channels</h1>
<p>Watch the <a href="/cur">current channel</a> (%s) - %d viewers.</p>
<ul>%s</ul></body></html>"""
CHUNK_SIZE = 49820 # multiple of 188 bytes to fall on MPEG-TS packet
                   # boundaries
CHAN_PATH = os.path.expanduser('~/.tzap/channels.conf')
channels = set()
DEVNULL = open('/dev/null', 'rb')

cur_user_lock = threading.RLock()
cur_users = 0
cur_chan = ''
feed_data_event = threading.Event()
feed_head = 0
feed_buffer = [None] * 200 # ring buffer with multiple lockless readers

class ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
  daemon_threads = True

def hard_read(s, l):
  """Read l number of bytes from s before returning"""
  data = []
  while l > 0:
    d = s.read(l)
    if not d:
      return None
    data.append(d)
    l -= len(d)
  return b''.join(data)

def supperr(f, *args, **kwargs):
  try:
    f(*args, **kwargs)
  except:
    pass

def reader(s):
  """Write the ring buffer from MPEG-TS data"""
  global feed_head
  while True:
    data = hard_read(s, CHUNK_SIZE)
    if not data:
      break
    feed_buffer[feed_head] = data
    feed_head = (feed_head + 1) % len(feed_buffer)
    feed_data_event.set()
    feed_data_event.clear()
  for i in range(len(feed_buffer)):
    feed_buffer[i] = None

def streamer():
  """Stream the ring buffer data through HTTP to viewers"""
  global cur_users
  with cur_user_lock:
    cur_users += 1
  try:
    my_head = feed_head
    while True:
      while my_head == feed_head:
        feed_data_event.wait()
      data = feed_buffer[my_head]
      my_head = (my_head + 1) % len(feed_buffer)
      if data:
        yield data
  finally:
    with cur_user_lock:
      cur_users -= 1

def feeder():
  """Manage the processes reading the live TV data from tuner"""
  p1, p2, thread, old_chan = None, None, None, None
  try:
    while cur_chan:
      if ((p1 and p1.poll() is not None)
          or (p2 and p2.poll() is not None)):
        print("dvbbc: gnutv.ret == %r, ffmpeg.ret == %r" % (
          p1.returncode, p2.returncode), file=sys.stderr)
        old_chan = None
      if cur_chan and old_chan != cur_chan:
        old_chan = cur_chan
        if p1: supperr(p1.kill)
        if p2: supperr(p2.kill)
        p1 = Popen([
          'gnutv', '-channels', CHAN_PATH, '-out', 'stdout', cur_chan
        ], stdout=PIPE)
        p2 = Popen([
          'ffmpeg', '-loglevel', 'fatal', '-i','-', '-acodec', 'copy',
          '-vcodec', 'copy', '-scodec', 'copy', '-f', 'mpegts', '-'
        ], stdout=PIPE, stdin=p1.stdout, bufsize=1, close_fds=True)
        p1.stdout.close()
        thread = threading.Thread(target=reader, args=(p2.stdout,))
        thread.daemon = True
        thread.start()
      time.sleep(0.25)
  finally:
    if p1: supperr(p1.kill)
    if p2: supperr(p2.kill)

def simple_app(environ, start_response):
  """A simple WSGI app"""
  global cur_chan
  try:
      if environ['PATH_INFO'] == '/':
        start_response('200 OK', [('Content-type', 'text/html')])
        chans = '\n'.join(
          '<li><a href="/chan/%s">%s</a></li>' % (urlenc(c), htmlenc(c))
          for c in sorted(channels)
        )
        return [(CHANS_TPL % (htmlenc(cur_chan), cur_users, chans))
                .encode('utf8')]
      elif environ['PATH_INFO'] == '/cur':
        start_response('200 OK', [('Content-type', 'video/MP2T')])
        return streamer()
      elif environ['PATH_INFO'].startswith('/chan/'):
        ch = urldec(environ['PATH_INFO'][len('/chan/'):])
        if ch in channels:
          start_response('200 OK', [('Content-type', 'video/MP2T')])
          cur_chan = ch
          return streamer()
        else:
          start_response('404 Not found', [('Content-type', 'text/plain')])
          return [("Invalid channel '%s'" % ch).encode('utf8')]
      else:
        start_response('404 Not found', [('Content-type', 'text/plain')])
        return ["Page not found".encode('utf8')]
    except:
        print("lala")

def dtvmode(mode):
    """ Set digital TV mode for device """
    with Popen(['/opt/bin/mediaclient', '-D', mode], stdout=PIPE) as proc:
        if proc.wait()==0:
            print(proc.communicate()[0])
            return True
        else:
            return False


def main():
  """Run the show"""
  global cur_chan

  #Arguments parser
  parser = argparse.ArgumentParser(description="Stream live TV over HTTP to multiple viewers, using Sundtek as capture card")
  parser.add_argument("-p","--port",type=int,default=2000,help="server port")
  parser.add_argument("-D", "--dtvmode",type=str,choices=["DVBT", "DVBC", "ATSC","ISDBT"],default="ISDBT",help="set digital TV mode for device")
  args=parser.parse_args()

  #Setting dtv mode using mediaclient
  if dtvmode(args.dtvmode):

      #Get channels from file
      channels.update(set(
        l.split(':')[0] for l in open(CHAN_PATH, 'r')
      ))
      cur_chan = list(channels)[0]

      feed_thread = threading.Thread(target=feeder)
      feed_thread.daemon = True
      feed_thread.start()

      validator_app = validator(simple_app)
      httpd = make_server(
        '', args.port, validator_app,
        server_class=ThreadedWSGIServer
      )
      try:
        httpd.serve_forever()
      finally:
        cur_chan = None
        feed_thread.join()
  else:
        print("Error setting the dtv mode")

if __name__ == '__main__':
  main()
