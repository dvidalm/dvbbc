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




DEVNULL = open('/dev/null', 'rb')
#
# cur_user_lock = threading.RLock()
# cur_chan = ''
# feed_data_event = threading.Event()
# feed_head = 0
chunk_size = 49820 # multiple of 188 bytes to fall on MPEG-TS packet
                   # boundaries


class ThreadedWSGIServer(ThreadingMixIn, WSGIServer):
  daemon_threads = True


class Server():

    def __init__(self):
        self.chan_path = os.path.expanduser('~/.tzap/channels.conf')
        self.feed_buffer = [None] * 200 # ring buffer with multiple lockless readers
        self.feed_head = 0
        self.cur_users = 0
        self.cur_user_lock = threading.RLock()
        self.feed_data_event = threading.Event()
        self.chans_tpl = """<!DOCTYPE html><html><body><h1>Channels</h1>
        <p>Watch the <a href="/cur">current channel</a> (%s) - %d viewers.</p>
        <ul>%s</ul></body></html>"""
        self.channels = set()
        self.channels.update(set(
          l.split(':')[0] for l in open(self.chan_path, 'r')
        ))
        self.cur_chan = list(self.channels)[0]


    def hard_read(self,s,l):
      """Read l number of bytes from s before returning"""
      data = []
      while l > 0:
        d = s.read(l)
        if not d:
          return None
        data.append(d)
        l -= len(d)
      return b''.join(data)

    def supperr(self,f, *args, **kwargs):
      try:
        f(*args, **kwargs)
      except:
        pass

    def reader(self,s):
      """Write the ring buffer from MPEG-TS data"""
      self.feed_head=0
      while True:
        data = self.hard_read(s, chunk_size)
        if not data:
          break
        self.feed_buffer[self.feed_head] = data
        self.feed_head = (self.feed_head + 1) % len(self.feed_buffer)
        self.feed_data_event.set()
        self.feed_data_event.clear()
      for i in range(len(self.feed_buffer)):
        self.feed_buffer[i] = None

    def streamer(self):
      """Stream the ring buffer data through HTTP to viewers"""
      with self.cur_user_lock:
        self.cur_users += 1
      try:
        my_head = self.feed_head
        while True:
          while my_head == self.feed_head:
            self.feed_data_event.wait()
          data = self.feed_buffer[my_head]
          my_head = (my_head + 1) % len(self.feed_buffer)
          if data:
            yield data
      finally:
        with self.cur_user_lock:
          self.cur_users -= 1

    def feeder(self):
      """Manage the processes reading the live TV data from tuner"""
      p1, p2, thread, old_chan = None, None, None, None
      try:
        while self.cur_chan:
          if ((p1 and p1.poll() is not None)
              or (p2 and p2.poll() is not None)):
            print("dvbbc: gnutv.ret == %r, ffmpeg.ret == %r" % (
              p1.returncode, p2.returncode), file=sys.stderr)
            old_chan = None
          if self.cur_chan and old_chan != self.cur_chan:
            old_chan = self.cur_chan
            if p1: self.supperr(p1.kill)
            if p2: self.supperr(p2.kill)
            p1 = Popen([
              'gnutv', '-channels', self.chan_path, '-out', 'stdout', self.cur_chan
            ], stdout=PIPE)
            p2 = Popen([
              'ffmpeg', '-loglevel', 'fatal', '-i','-', '-acodec', 'copy',
              '-vcodec', 'copy', '-scodec', 'copy', '-f', 'mpegts', '-'
            ], stdout=PIPE, stdin=p1.stdout, bufsize=1, close_fds=True)
            p1.stdout.close()
            thread = threading.Thread(target=self.reader, args=(p2.stdout,))
            thread.daemon = True
            thread.start()
          time.sleep(0.25)
      finally:
        if p1: self.supperr(p1.kill)
        if p2: self.supperr(p2.kill)

    def simple_app(self,environ, start_response):
      """A simple WSGI app"""
      if environ['PATH_INFO'] == '/stream':
         start_response('200 OK', [('Content-type', 'video/MP2T')])
         return self.streamer()
      else:
        start_response('404 Not found', [('Content-type', 'text/plain')])
        return ["Page not found".encode('utf8')]

    def set_channel(self,channel):
        self.cur_chan = channel



def dtvmode(mode):
    """ Set digital TV mode for device """
    with Popen(['/opt/bin/mediaclient', '-D', mode], stdout=PIPE) as proc:
        if proc.wait()==0:
            print(proc.communicate()[0])
            return True
        else:
            return False


def select_channel(channels):
    print("Choose a channel:")
    count = 1
    for channel in channels:
        print(str(count)+". "+channel)
        count +=1
    ch=int(input())
    return channels[ch-1]




def main():
    """Run the show"""

    #Arguments parser
    parser = argparse.ArgumentParser(description="Stream live TV over HTTP to multiple viewers, using Sundtek as capture card")
    parser.add_argument("-p","--port",type=int,default=2000,help="server port")
    parser.add_argument("-D", "--dtvmode",type=str,choices=["DVBT", "DVBC", "ATSC","ISDBT"],default="ISDBT",help="set digital TV mode for device")
    args=parser.parse_args()

    #Setting dtv mode using mediaclient
    if dtvmode(args.dtvmode):

      server = Server()
      #Select channel
      channel = select_channel(list(server.channels))
      server.set_channel(channel)

      feed_thread = threading.Thread(target=server.feeder)
      feed_thread.daemon = True
      feed_thread.start()

      validator_app = validator(server.simple_app)
      httpd = make_server('', args.port, validator_app,server_class=ThreadedWSGIServer)
      try:
        httpd.serve_forever()
      finally:
        server.cur_chan = None
        feed_thread.join()
    else:
        print("Error setting the dtv mode")

if __name__ == '__main__':
    main()
