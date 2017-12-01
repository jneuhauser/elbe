#
# ELBE - Debian Based Embedded Rootfilesystem Builder
# Copyright (C) 2014,2017 Linutronix GmbH
#
# This file is part of ELBE.
#
# ELBE is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# ELBE is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with ELBE.  If not, see <http://www.gnu.org/licenses/>.

import os

class Config(dict):
    def __init__(self):
        self['soaphost'] = "localhost"
        self['soapport'] = "7587"
        self['elbeuser'] = "root"
        self['elbepass'] = "foo"
        self['pbuilder_jobs'] = "auto"

        if 'ELBE_SOAPPORT' in os.environ:
            self['soapport'] = os.environ['ELBE_SOAPPORT']

        if 'ELBE_SOAPHOST' in os.environ:
            self['soaphost'] = os.environ['ELBE_SOAPHOST']

        if 'ELBE_USER' in os.environ:
            self['elbeuser'] = os.environ['ELBE_USER']

        if 'ELBE_PASS' in os.environ:
            self['elbepass'] = os.environ['ELBE_PASS']

        if 'ELBE_PBUILDER_JOBS' in os.environ:
            self['pbuilder_jobs'] = os.environ['ELBE_PBUILDER_JOBS']


cfg = Config()

