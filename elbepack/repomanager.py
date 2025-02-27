# ELBE - Debian Based Embedded Rootfilesystem Builder
# Copyright (c) 2014 Stefan Gast <stefan.gast@linutronix.de>
# Copyright (c) 2014-2016 Torben Hohn <torben.hohn@linutronix.de>
# Copyright (c) 2014-2017 Manuel Traut <manut@linutronix.de>
# Copyright (c) 2014 Andreas Messerschmid <andreas@linutronix.de>
# Copyright (c) 2016 John Ogness <john.ogness@linutronix.de>
#
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import shutil

from debian.deb822 import Deb822

from elbepack.debianreleases import codename2suite
from elbepack.filesystem import Filesystem
from elbepack.pkgutils import get_dsc_size
from elbepack.egpg import generate_elbe_internal_key, export_key, unlock_key
from elbepack.shellhelper import CommandError


class RepoAttributes(object):
    def __init__(self, codename, arch, components,
                 mirror='http://ftp.de.debian.org/debian'):
        self.codename = codename
        if isinstance(arch, str):
            self.arch = set([arch])
        else:
            self.arch = set(arch)

        if isinstance(components, str):
            self.components = set([components])
        else:
            self.components = set(components)

        self.mirror = mirror

    def __add__(self, other):
        """ Over simplistic Add implementation only useful for
            our current implementation"""

        if other.codename != self.codename:
            return [self, other]

        assert self.mirror == other.mirror
        ret_arch = self.arch.union(other.arch)
        ret_comp = self.components.union(other.components)

        return [RepoAttributes(self.codename, ret_arch, ret_comp, self.mirror)]


class RepoBase(object):

    # pylint: disable=too-many-instance-attributes

    def __init__(
            self,
            path,
            log,
            init_attr,
            repo_attr,
            origin,
            description,
            maxsize=None):

        # pylint: disable=too-many-arguments

        self.vol_path = path
        self.volume_count = 0

        self.log = log
        self.init_attr = init_attr
        self.repo_attr = repo_attr

        if init_attr is not None and repo_attr is not None:
            self.attrs = init_attr + repo_attr
        elif repo_attr is not None:
            self.attrs = [repo_attr]
        elif init_attr is not None:
            self.attrs = [init_attr]

        self.origin = origin
        self.description = description
        self.maxsize = maxsize
        self.fs = self.get_volume_fs(self.volume_count)

        # if repo exists retrive the keyid otherwise
        # generate a new key and generate repository config
        if self.fs.isdir("/"):
            repo_conf = self.fs.read_file("conf/distributions")
            for l in repo_conf.splitlines():
                if l.startswith("SignWith"):
                    self.keyid = l.split()[1]
                    unlock_key(self.keyid)
        else:
            self.keyid = generate_elbe_internal_key()
            unlock_key(self.keyid)
            self.gen_repo_conf()

    def get_volume_fs(self, volume):
        if self.maxsize:
            volname = os.path.join(self.vol_path, "vol%02d" % volume)
            return Filesystem(volname)

        return Filesystem(self.vol_path)

    def new_repo_volume(self):
        self.volume_count += 1
        self.fs = self.get_volume_fs(self.volume_count)
        self.gen_repo_conf()

    def gen_repo_conf(self):
        self.fs.mkdir_p("conf")
        fp = self.fs.open("conf/distributions", "w")

        need_update = False

        for att in self.attrs:
            fp.write("Origin: " + self.origin + "\n")
            fp.write("Label: " + self.origin + "\n")
            fp.write("Suite: " + codename2suite[att.codename] + "\n")
            fp.write("Codename: " + att.codename + "\n")
            fp.write("Architectures: " + " ".join(att.arch) + "\n")
            fp.write("Components: " + " ".join(att.components.difference(
                set(["main/debian-installer"]))) + "\n")
            fp.write("UDebComponents: " + " ".join(att.components.difference(
                set(["main/debian-installer"]))) + "\n")
            fp.write("Description: " + self.description + "\n")
            fp.write("SignWith: " + self.keyid + "\n")

            if 'main/debian-installer' in att.components:
                fp.write("Update: di\n")

                ufp = self.fs.open("conf/updates", "w")

                ufp.write("Name: di\n")
                ufp.write("Method: " + att.mirror + "\n")
                ufp.write("VerifyRelease: blindtrust\n")
                ufp.write("Components: \n")
                ufp.write("GetInRelease: no\n")
                # It would be nicer, to use this
                # ufp.write( "Architectures: " + " ".join (att.arch) + "\n" )
                # But we end up with 'armel amd64' sometimes.
                # So lets just use the init_attr...
                if self.init_attr:
                    ufp.write(
                        "Architectures: " +
                        " ".join(
                            self.init_attr.arch) +
                        "\n")
                else:
                    ufp.write("Architectures: " + " ".join(att.arch) + "\n")

                ufp.write("UDebComponents: main>main\n")
                ufp.close()

                need_update = True

            fp.write("\n")
        fp.close()

        keyring = export_key(self.keyid, self.fs.fname("/repo.pub"))
        if keyring:
            shutil.copyfile(keyring, self.fs.fname("/elbe-keyring.gpg"))

        if need_update:
            self.log.do(
                'reprepro --export=force --basedir "' +
                self.fs.path +
                '" update',
                env_add={'GNUPGHOME': "/var/cache/elbe/gnupg"})
        else:
            for att in self.attrs:
                self.log.do(
                    'reprepro --basedir "' +
                    self.fs.path +
                    '" export ' +
                    att.codename,
                    env_add={'GNUPGHOME': "/var/cache/elbe/gnupg"})

    def finalize(self):
        for att in self.attrs:
            self.log.do(
                'reprepro --basedir "' +
                self.fs.path +
                '" export ' +
                att.codename,
                env_add={'GNUPGHOME': '/var/cache/elbe/gnupg'})

    def _includedeb(self, path, codename, component):
        if self.maxsize:
            new_size = self.fs.disk_usage("") + os.path.getsize(path)
            if new_size > self.maxsize:
                self.new_repo_volume()

        self.log.do(
            'reprepro --keepunreferencedfiles --export=never --basedir "' +
            self.fs.path +
            '" -C ' +
            component +
            ' includedeb ' +
            codename +
            ' ' +
            path)

    def includedeb(self, path, component="main", pkgname=None, force=False):
        # pkgname needs only to be specified if force is enabled
        try:
            self._includedeb(path, self.repo_attr.codename, component)
        except CommandError as ce:
            if force and pkgname is not None:
                # Including deb did not work.
                # Maybe we have the same Version with a
                # different md5 already.
                #
                # Try remove, and add again.
                self.removedeb(pkgname, component)
                self._includedeb(path, self.repo_attr.codename, component)
            else:
                raise ce

    def include_init_deb(self, path, component="main"):
        self._includedeb(path, self.init_attr.codename, component)

    def _include(self, path, codename, component):
        self.log.do('reprepro --ignore=wrongdistribution '
                    '--ignore=surprisingbinary --keepunreferencedfiles '
                    '--export=never --basedir "' + self.fs.path + '" -C ' +
                    component + ' -P normal -S misc include ' + codename +
                    ' ' + path)

    def _removedeb(self, pkgname, codename):
        self.log.do(
            "reprepro --basedir %s remove %s %s" %
            (self.fs.path, codename, pkgname),
            env_add={'GNUPGHOME': '/var/cache/elbe/gnupg'})

    def removedeb(self, pkgname, component="main"):
        self._removedeb(pkgname, self.repo_attr.codename)

    def _removesrc(self, srcname, codename):
        self.log.do(
            "reprepro --basedir %s removesrc %s %s" %
            (self.fs.path, codename, srcname),
            env_add={'GNUPGHOME': '/var/cache/elbe/gnupg'})

    def removesrc(self, path, component="main"):
        for p in Deb822.iter_paragraphs(file(path)):
            if 'Source' in p:
                self._removesrc(p['Source'], self.repo_attr.codename)

    def _remove(self, path, codename, component):
        for p in Deb822.iter_paragraphs(file(path)):
            if 'Source' in p:
                self._removesrc(p['Source'], codename)
            elif 'Package' in p:
                self._removedeb(p['Package'], codename)
            elif 'Binary' in p:
                for pp in p['Binary'].split():
                    self._removedeb(pp, codename)


    def _includedsc(self, path, codename, component):
        if self.maxsize:
            new_size = self.fs.disk_usage("") + get_dsc_size(path)
            if new_size > self.maxsize:
                self.new_repo_volume()

        if self.maxsize and (self.fs.disk_usage("") > self.maxsize):
            self.new_repo_volume()

        self.log.do(
            'reprepro --keepunreferencedfiles --export=never --basedir "' +
            self.fs.path +
            '" -C ' +
            component +
            ' -P normal -S misc includedsc ' +
            codename +
            ' ' +
            path)

    def includedsc(self, path, component="main", force=False):
        try:
            self._includedsc(path, self.repo_attr.codename, component)
        except CommandError as ce:
            if ce.returncode == 251:
                # 251 is -5 (RET_ERROR_GPGME in reprepro source)
                #
                # gnupg2_2.1.18-8~deb9u3.dsc is signed using EdDSA
                # jessies gpg version does not support this.
                # expect more packages signed with EdDSA soon.
                #
                # copy the dsc into the cdrom root,
                # when reprepro fails to insert it.
                self.log.printo('Unable to verify dsc "%s":' % path)
                self.log.printo('unsupported signature algorithm')
                self.log.do('cp -av "%s" "%s"' % (path, self.fs.path))
            elif force:
                # Including dsc did not work.
                # Maybe we have the same Version with a
                # different md5 already.
                #
                # Try remove, and add again.
                self.removesrc(path, component)
                self._includedsc(path, self.repo_attr.codename, component)
            else:
                raise ce

    def include(self, path, component="main", force=False):
        if force:
            self._remove(path, self.repo_attr.codename, component)
        self._include(path, self.repo_attr.codename, component)

    def remove(self, path, component="main"):
        self._remove(path, self.repo_attr.codename, component)

    def include_init_dsc(self, path, component="main"):
        self._includedsc(path, self.init_attr.codename, component)

    def buildiso(self, fname):
        files = []
        if self.volume_count == 0:
            new_path = '"' + self.fs.path + '"'
            self.log.do(
                "genisoimage -o %s -J -joliet-long -R %s" %
                (fname, new_path))
            files.append(fname)
        else:
            for i in range(self.volume_count + 1):
                volfs = self.get_volume_fs(i)
                newname = fname + ("%02d" % i)
                self.log.do(
                    "genisoimage -o %s -J -joliet-long -R %s" %
                    (newname, volfs.path))
                files.append(newname)

        return files


class UpdateRepo(RepoBase):
    def __init__(self, xml, path, log):
        self.xml = xml

        arch = xml.text("project/arch", key="arch")
        codename = xml.text("project/suite")

        repo_attrs = RepoAttributes(codename, arch, "main")

        RepoBase.__init__(self,
                          path,
                          log,
                          None,
                          repo_attrs,
                          "Update",
                          "Update")


class CdromInitRepo(RepoBase):
    def __init__(self, init_codename, path, log, maxsize,
                 mirror='http://ftp.de.debian.org/debian'):

        # pylint: disable=too-many-arguments

        init_attrs = RepoAttributes(
            init_codename, "amd64", [
                "main", "main/debian-installer"], mirror)

        RepoBase.__init__(self,
                          path,
                          log,
                          None,
                          init_attrs,
                          "Elbe",
                          "Elbe InitVM Cdrom Repo",
                          maxsize)


class CdromBinRepo(RepoBase):
    def __init__(
            self,
            arch,
            codename,
            init_codename,
            path,
            log,
            maxsize,
            mirror='http://ftp.debian.org/debian'):

        # pylint: disable=too-many-arguments

        repo_attrs = RepoAttributes(codename, arch, ["main", "added"], mirror)
        if init_codename is not None:
            init_attrs = RepoAttributes(
                init_codename, "amd64", [
                    "main", "main/debian-installer"], mirror)
        else:
            init_attrs = None

        RepoBase.__init__(self,
                          path,
                          log,
                          init_attrs,
                          repo_attrs,
                          "Elbe",
                          "Elbe Binary Cdrom Repo",
                          maxsize)


class CdromSrcRepo(RepoBase):
    def __init__(self, codename, init_codename, path, log, maxsize,
                 mirror='http://ftp.debian.org/debian'):

        # pylint: disable=too-many-arguments

        repo_attrs = RepoAttributes(codename,
                                    "source",
                                    ["main", "added"],
                                    mirror)

        if init_codename is not None:
            init_attrs = RepoAttributes(init_codename,
                                        "source",
                                        ["initvm"],
                                        mirror)
        else:
            init_attrs = None

        RepoBase.__init__(self,
                          path,
                          log,
                          init_attrs,
                          repo_attrs,
                          "Elbe",
                          "Elbe Source Cdrom Repo",
                          maxsize)


class ToolchainRepo(RepoBase):
    def __init__(self, arch, codename, path, log):
        repo_attrs = RepoAttributes(codename, arch, "main")
        RepoBase.__init__(self,
                          path,
                          log,
                          None,
                          repo_attrs,
                          "toolchain",
                          "Toolchain binary packages Repo")


class ProjectRepo(RepoBase):
    def __init__(self, arch, codename, path, log):
        repo_attrs = RepoAttributes(codename, arch + ' source', "main")
        RepoBase.__init__(self,
                          path,
                          log,
                          None,
                          repo_attrs,
                          "Local",
                          "Self build packages Repo")
