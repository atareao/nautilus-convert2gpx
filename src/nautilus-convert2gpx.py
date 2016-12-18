#!/usr/bin/python
# -*- coding: utf-8 -*-
#
# This file is part of nautilus-convert2mp3
#
# Copyright (C) 2012-2016 Lorenzo Carbonell
# lorenzo.carbonell.cerezo@gmail.com
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
#
#
import gi
try:
    gi.require_version('Gtk', '3.0')
    gi.require_version('Nautilus', '3.0')
except Exception as e:
    print(e)
    exit(-1)
import os
from xml import sax
from xml.sax import saxutils
import StringIO
from threading import Thread
from urllib import unquote_plus
from gi.repository import GObject
from gi.repository import Gtk
from gi.repository import GLib
from gi.repository import Nautilus as FileManager

APPNAME = 'nautilus-convert2gpx'
ICON = 'nautilus-convert2gpx'
VERSION = '0.4.0'
_ = str

EXTENSIONS_FROM = ['.tcx']

"""Simple converter from TCX file to GPX format
Usage:   python tcx2gpx.py   foo.tcx  > foo.gpx
Streaming implementation works for large files.

Open Source: MIT Licencse.
This is or was <http://www.w3.org/2009/09/geo/tcx2gpx.py>
Author: http://www.w3.org/People/Berners-Lee/card#i
Written: 2009-10-30
Last change: $Date: 2009/10/28 13:44:33 $
"""

TCX_NS = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"

global output
output = StringIO.StringIO()


class MyHandler(sax.handler.ContentHandler,):
    global output

    def __init__(self):
        self.time = ""
        self.lat = ""
        self.lon = ""
        self.alt = ""
        self.content = ""

    def startDocument(self):
        output.write("""
<gpx xmlns="http://www.topografix.com/GPX/1/1"
creator="http://www.w3.org/2009/09/geo/tcx2gpx.py"
version="1.1"
xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
xsi:schemaLocation="http://www.topografix.com/GPX/1/1
http://www.topografix.com/GPX/1/1/gpx.xsd">
""")

    def get_gpx(self):
        contents = output.getvalue()
        output.close()
        return contents

    def endDocument(self):
        output.write('</gpx>\n')

    def startElement(self, name, attrs):

        self.content = ""
        if name == 'Track':
            output.write(' <trk>\n')

    def characters(self, content):
        self.content = self.content + saxutils.escape(content)

    def endElement(self, name):
        if name == 'Track':
            output.write(' </trk>\n')
        elif name == 'Trackpoint':
            output.write('  <trkpt lat="%s" lon="%s">\n' % (self.lat,
                                                            self.lon))
            if (self.alt):
                    output.write('   <ele>%s</ele>\n' % self.alt)
            if (self.time):
                output.write('   <time>%s</time>\n' % self.time)
            output.write('  </trkpt>\n')
            output.flush()
        elif name == 'LatitudeDegrees':
            self.lat = self.content
        elif name == 'LongitudeDegrees':
            self.lon = self.content
        elif name == 'AltitudeMeters':
            self.alt = self.content
        elif name == 'Time':
            self.time = self.content


class IdleObject(GObject.GObject):
    """
    Override GObject.GObject to always emit signals in the main thread
    by emmitting on an idle handler
    """
    def __init__(self):
        GObject.GObject.__init__(self)

    def emit(self, *args):
        GLib.idle_add(GObject.GObject.emit, self, *args)


class DoItInBackground(IdleObject, Thread):
    __gsignals__ = {
        'started': (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (int,)),
        'ended': (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (bool,)),
        'start_one': (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (str,)),
        'end_one': (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, (float,)),
    }

    def __init__(self, elements):
        IdleObject.__init__(self)
        Thread.__init__(self)
        self.elements = elements
        self.stopit = False
        self.ok = True
        self.daemon = True
        self.process = None

    def stop(self, *args):
        self.stopit = True
        if self.process is not None:
            self.process.terminate()

    def convert2gpx(self, file_in):
        output = StringIO.StringIO()
        handler = MyHandler()
        f = open(file_in, 'r')
        sax.parse(f, handler)
        f.close()
        file_out = get_output_filename(file_in)
        outputfile = open(file_out, 'w')
        outputfile.write(output.getvalue())
        outputfile.close()
        output.close()

    def run(self):
        total = 0
        for element in self.elements:
            total += get_duration(element)
        self.emit('started', total)
        try:
            total = 0
            for element in self.elements:
                if self.stopit is True:
                    self.ok = False
                    break
                self.emit('start_one', element)
                self.convert2gpx(element)
                self.emit('end_one', get_duration(element))
        except Exception as e:
            self.ok = False
        try:
            if self.process is not None:
                self.process.terminate()
                self.process = None
        except Exception as e:
            print(e)
        self.emit('ended', self.ok)


class Progreso(Gtk.Dialog, IdleObject):
    __gsignals__ = {
        'i-want-stop': (GObject.SIGNAL_RUN_FIRST, GObject.TYPE_NONE, ()),
    }

    def __init__(self, title, parent):
        Gtk.Dialog.__init__(self, title, parent,
                            Gtk.DialogFlags.MODAL |
                            Gtk.DialogFlags.DESTROY_WITH_PARENT)
        IdleObject.__init__(self)
        self.set_position(Gtk.WindowPosition.CENTER_ALWAYS)
        self.set_size_request(330, 30)
        self.set_resizable(False)
        self.connect('destroy', self.close)
        self.set_modal(True)
        vbox = Gtk.VBox(spacing=5)
        vbox.set_border_width(5)
        self.get_content_area().add(vbox)
        #
        frame1 = Gtk.Frame()
        vbox.pack_start(frame1, True, True, 0)
        table = Gtk.Table(2, 2, False)
        frame1.add(table)
        #
        self.label = Gtk.Label()
        table.attach(self.label, 0, 2, 0, 1,
                     xpadding=5,
                     ypadding=5,
                     xoptions=Gtk.AttachOptions.SHRINK,
                     yoptions=Gtk.AttachOptions.EXPAND)
        #
        self.progressbar = Gtk.ProgressBar()
        self.progressbar.set_size_request(300, 0)
        table.attach(self.progressbar, 0, 1, 1, 2,
                     xpadding=5,
                     ypadding=5,
                     xoptions=Gtk.AttachOptions.SHRINK,
                     yoptions=Gtk.AttachOptions.EXPAND)
        button_stop = Gtk.Button()
        button_stop.set_size_request(40, 40)
        button_stop.set_image(
            Gtk.Image.new_from_stock(Gtk.STOCK_STOP, Gtk.IconSize.BUTTON))
        button_stop.connect('clicked', self.on_button_stop_clicked)
        table.attach(button_stop, 1, 2, 1, 2,
                     xpadding=5,
                     ypadding=5,
                     xoptions=Gtk.AttachOptions.SHRINK)
        self.stop = False
        self.show_all()
        self.value = 0.0

    def set_max_value(self, anobject, max_value):
        self.max_value = float(max_value)

    def get_stop(self):
        return self.stop

    def on_button_stop_clicked(self, widget):
        self.stop = True
        self.emit('i-want-stop')

    def close(self, *args):
        self.destroy()

    def increase(self, anobject, value):
        self.value += float(value)
        fraction = self.value/self.max_value
        self.progressbar.set_fraction(fraction)
        if self.value >= self.max_value:
            self.hide()

    def set_element(self, anobject, element):
        self.label.set_text(_('Converting: %s') % element)


def get_output_filename(file_in):
    head, tail = os.path.split(file_in)
    root, ext = os.path.splitext(tail)
    file_out = os.path.join(head, root+'.gpx')
    return file_out


def get_duration(file_in):
    return os.path.getsize(file_in)


class GPXConverterMenuProvider(GObject.GObject, Nautilus.MenuProvider):
    """
    Implements the 'Replace in Filenames' extension to the File Manager\
    right-click menu
    """

    def __init__(self):
        """
        File Manager crashes if a plugin doesn't implement the __init__\
        method
        """
        pass

    def all_files_are_tcx(self, items):
        for item in items:
            fileName, fileExtension = os.path.splitext(
                unquote_plus(item.get_uri()[7:]))
            if fileExtension.lower() in EXTENSIONS_FROM:
                return True
        return False

    def convert(self, menu, selected, window):
        files = get_files(selected)
        diib = DoItInBackground(files)
        progreso = Progreso(_('Convert to mp3'), window)
        diib.connect('started', progreso.set_max_value)
        diib.connect('start_one', progreso.set_element)
        diib.connect('end_one', progreso.increase)
        diib.connect('ended', progreso.close)
        progreso.connect('i-want-stop', diib.stop)
        diib.start()
        progreso.run()

    def get_file_items(self, window, sel_items):
        """
        Adds the 'Replace in Filenames' menu item to the File Manager\
        right-click menu, connects its 'activate' signal to the 'run'\
        method passing the selected Directory/File
        """
        if self.all_files_are_sounds(sel_items):
            top_menuitem = FileManager.MenuItem(
                name='GPXConverterMenuProvider::Gtk-convert2gpx-top',
                label=_('Convert to gpx'),
                tip=_('Tool to convert to gpx'))
            submenu = FileManager.Menu()
            top_menuitem.set_submenu(submenu)

            sub_menuitem_00 = FileManager.MenuItem(
                name='GPXConverterMenuProvider::Gtk-convert2gpx-sub-01',
                label=_('Convert'),
                tip=_('Tool to convert to gpx'))
            sub_menuitem_00.connect('activate',
                                    self.convert,
                                    sel_items,
                                    window)
            submenu.append_item(sub_menuitem_00)
            sub_menuitem_01 = FileManager.MenuItem(
                name='GPXConverterMenuProvider::Gtk-convert2gpx-sub-02',
                label=_('About'),
                tip=_('About'))
            sub_menuitem_01.connect('activate', self.about, window)
            submenu.append_item(sub_menuitem_01)
            #
            return top_menuitem,
        return

    def about(self, widget, window):
        ad = Gtk.AboutDialog(parent=window)
        ad.set_name(APPNAME)
        ad.set_version(VERSION)
        ad.set_copyright('Copyrignt (c) 2016\nLorenzo Carbonell')
        ad.set_comments(APPNAME)
        ad.set_license('''
This program is free software: you can redistribute it and/or modify it under
the terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT
ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with
this program. If not, see <http://www.gnu.org/licenses/>.
''')
        ad.set_website('http://www.atareao.es')
        ad.set_website_label('http://www.atareao.es')
        ad.set_authors([
            'Lorenzo Carbonell <lorenzo.carbonell.cerezo@gmail.com>'])
        ad.set_documenters([
            'Lorenzo Carbonell <lorenzo.carbonell.cerezo@gmail.com>'])
        ad.set_icon_name(ICON)
        ad.set_logo_icon_name(APPNAME)
        ad.run()
        ad.destroy()
