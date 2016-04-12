Introduction
============

_dvbbc_ allows streaming live TV over HTTP to multiple viewers, using Sundtek TV capturer. It is as
simple as a design one can get.

Setup
=====

 1. Install Sundtek drivers. Follow the instructions [here](http://support.sundtek.com/index.php/topic,4.0.html)

 2. Install `dvb-apps` and `ffmpeg` for your distribution

 3. [Scan and setup all your channels][scan] using `scan`

 4. Copy the channel configuration to `.tzap/channels.conf`


Usage
=====

 1. Run `python3 dvbbc.py`
 2. Select channel
 3. Visit `http://localhost/stream` or use vlc to see the streaming video


Options
=====

```-p, --port``` : Server port.<br/>
```-D {DVBT,DVBC,ATSC,ISDBT}, --dtvmode {DVBT,DVBC,ATSC,ISDBT}``` : Set digital TV mode for device.<br/>

Notes
=====

When everything is set up, you want to keep it running. You have
countless choices here but I opted for [supervisord][]. I've provided a
sample config file [`dvbbc.ini`][config] if you chose to go with
_supervisord_.

[supervisord]: http://supervisord.org/
[scan]: http://www.linuxtv.org/wiki/index.php/Scan
[config]: dvbbc.ini
