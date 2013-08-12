# -*- coding: utf-8 -*-
#
# Copyright © 2013 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public
# License as published by the Free Software Foundation; either version
# 2 of the License (GPLv2) or (at your option) any later version.
# There is NO WARRANTY for this software, express or implied,
# including the implied warranties of MERCHANTABILITY,
# NON-INFRINGEMENT, or FITNESS FOR A PARTICULAR PURPOSE. You should
# have received a copy of GPLv2 along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.

from cStringIO import StringIO
import os
import tarfile
import unittest

import mock
from pulp.plugins.conduits.repo_publish import RepoPublishConduit
from pulp.plugins.config import PluginCallConfiguration
from pulp.plugins.model import Repository, AssociatedUnit, PublishReport

from pulp_puppet.common import constants
from pulp_puppet.plugins.distributors import installdistributor


class TestEntryPoint(unittest.TestCase):
    def test_everything(self):
        """everything isn't much"""
        plugin_class, config = installdistributor.entry_point()

        self.assertTrue(plugin_class is installdistributor.PuppetModuleInstallDistributor)
        # there is never a global config for this distributor
        self.assertEqual(config, {})


class TestValidateConfig(unittest.TestCase):
    def setUp(self):
        self.distributor = installdistributor.PuppetModuleInstallDistributor()
        self.repo = Repository('repo1', '', {})

    def test_not_present(self):
        config = PluginCallConfiguration({}, {})

        result, message = self.distributor.validate_config(self.repo, config, [])

        self.assertTrue(result)

    def test_relative_path(self):
        config = PluginCallConfiguration({}, {constants.CONFIG_INSTALL_PATH: 'a/b/c'})

        result, message = self.distributor.validate_config(self.repo, config, [])

        self.assertFalse(result)

    def test_path_does_not_exist(self):
        config = PluginCallConfiguration({}, {constants.CONFIG_INSTALL_PATH: '/a/b/c'})

        result, message = self.distributor.validate_config(self.repo, config, [])

        self.assertFalse(result)

    def test_path_is_not_dir(self):
        config = PluginCallConfiguration({}, {constants.CONFIG_INSTALL_PATH: __file__})

        result, message = self.distributor.validate_config(self.repo, config, [])

        self.assertFalse(result)

    def test_without_permission(self):
        # you're not running your tests as root, RIGHT?
        config = PluginCallConfiguration({}, {constants.CONFIG_INSTALL_PATH: '/root'})

        result, message = self.distributor.validate_config(self.repo, config, [])

        self.assertFalse(result)

    def test_with_permission(self):
        # you're not running your tests as root, RIGHT?
        config = PluginCallConfiguration({}, {constants.CONFIG_INSTALL_PATH: '/tmp'})

        result, message = self.distributor.validate_config(self.repo, config, [])

        self.assertTrue(result)


class TestPublishRepo(unittest.TestCase):
    def setUp(self):
        self.distributor = installdistributor.PuppetModuleInstallDistributor()
        self.repo = Repository('repo1', '', {})
        self.conduit = RepoPublishConduit('repo1', self.distributor.metadata()['id'])
        self.uk1 = {'author': 'puppetlabs', 'name': 'stdlib', 'version': '1.2.0'}
        self.uk2 = {'author': 'puppetlabs', 'name': 'stdlib', 'version': '1.2.1'}
        self.units = [
            AssociatedUnit(constants.TYPE_PUPPET_MODULE, self.uk1, {}, '/a/b/x', '', '', '', ''),
            AssociatedUnit(constants.TYPE_PUPPET_MODULE, self.uk2, {}, '/a/b/y', '', '', '', ''),
        ]
        self.conduit.get_units = mock.MagicMock(return_value=self.units, spec_set=self.conduit.get_units)

    @mock.patch('tarfile.open', autospec=True)
    @mock.patch.object(installdistributor.PuppetModuleInstallDistributor,
                       '_clear_destination_directory',
                       return_value=None)
    @mock.patch.object(installdistributor.PuppetModuleInstallDistributor,
                       '_check_for_unsafe_archive_paths',
                       return_value=None)
    def test_workflow(self, mock_check_paths, mock_clear, mock_open):
        config = PluginCallConfiguration({}, {constants.CONFIG_INSTALL_PATH: '/tmp'})

        report = self.distributor.publish_repo(self.repo, self.conduit, config)

        self.assertTrue(isinstance(report, PublishReport))
        self.assertTrue(report.success_flag)
        self.assertEqual(len(report.details['errors']), 0)
        self.assertEqual(len(report.details['success_unit_keys']), 2)
        self.assertTrue(self.uk1 in report.details['success_unit_keys'])
        self.assertTrue(self.uk2 in report.details['success_unit_keys'])

        self.assertEqual(mock_open.call_count, 2)
        mock_open.assert_any_call(self.units[0].storage_path)
        mock_open.assert_any_call(self.units[1].storage_path)

        mock_clear.assert_called_once_with('/tmp')

        mock_check_paths.assert_called_once_with(self.units, '/tmp')

    def test_no_destination(self):
        """this one should fail very early since the destination is missing"""
        config = PluginCallConfiguration({}, {})

        report = self.distributor.publish_repo(self.repo, self.conduit, config)

        self.assertFalse(report.success_flag)
        self.assertEqual(len(report.details['errors']), 0)
        self.assertEqual(len(report.details['success_unit_keys']), 0)

    @mock.patch.object(installdistributor.PuppetModuleInstallDistributor,
                       '_check_for_unsafe_archive_paths',
                       return_value=None)
    def test_unsafe_paths(self, mock_check):
        config = PluginCallConfiguration({}, {constants.CONFIG_INSTALL_PATH: '/tmp'})
        mock_check.side_effect = self._add_error

        report = self.distributor.publish_repo(self.repo, self.conduit, config)

        self.assertFalse(report.success_flag)
        self.assertEqual(len(report.details['errors']), 1)
        self.assertEqual(len(report.details['success_unit_keys']), 0)

    @mock.patch.object(installdistributor.PuppetModuleInstallDistributor,
                       '_check_for_unsafe_archive_paths',
                       return_value=None)
    @mock.patch.object(installdistributor.PuppetModuleInstallDistributor,
                       '_clear_destination_directory',
                       side_effect=OSError)
    def test_cannot_clear_destination(self, mock_clear, mock_check):
        config = PluginCallConfiguration({}, {constants.CONFIG_INSTALL_PATH: '/tmp'})

        report = self.distributor.publish_repo(self.repo, self.conduit, config)

        self.assertFalse(report.success_flag)
        self.assertEqual(len(report.details['errors']), 0)
        self.assertEqual(len(report.details['success_unit_keys']), 0)

    @mock.patch.object(installdistributor.PuppetModuleInstallDistributor,
                       '_check_for_unsafe_archive_paths',
                       return_value=None)
    @mock.patch.object(installdistributor.PuppetModuleInstallDistributor,
                       '_clear_destination_directory',
                       return_value=None)
    def test_cannot_open_tarballs(self, mock_clear, mock_check):
        """
        This is easy to simulate, because we can let the real tarfile module try
        to open the fake paths.
        """
        config = PluginCallConfiguration({}, {constants.CONFIG_INSTALL_PATH: '/tmp'})

        report = self.distributor.publish_repo(self.repo, self.conduit, config)

        self.assertFalse(report.success_flag)
        self.assertEqual(len(report.details['errors']), 2)
        self.assertTrue(report.details['errors'][0][0] in [self.uk1, self.uk2])
        self.assertTrue(report.details['errors'][1][0] in [self.uk1, self.uk2])
        self.assertEqual(len(report.details['success_unit_keys']), 0)

    @mock.patch('tarfile.open', autospec=True)
    @mock.patch.object(installdistributor.PuppetModuleInstallDistributor,
                       '_check_for_unsafe_archive_paths',
                       return_value=None)
    @mock.patch.object(installdistributor.PuppetModuleInstallDistributor,
                       '_clear_destination_directory',
                       return_value=None)
    def test_cannot_extract_tarballs(self, mock_clear, mock_check, mock_open):
        config = PluginCallConfiguration({}, {constants.CONFIG_INSTALL_PATH: '/tmp'})
        mock_open.return_value.extractall.side_effect = OSError

        report = self.distributor.publish_repo(self.repo, self.conduit, config)

        self.assertFalse(report.success_flag)
        self.assertEqual(len(report.details['errors']), 2)
        self.assertTrue(report.details['errors'][0][0] in [self.uk1, self.uk2])
        self.assertTrue(report.details['errors'][1][0] in [self.uk1, self.uk2])
        self.assertEqual(len(report.details['success_unit_keys']), 0)

    @mock.patch.object(installdistributor.PuppetModuleInstallDistributor,
                       '_clear_destination_directory',
                       return_value=None)
    def test_no_units(self, mock_clear):
        config = PluginCallConfiguration({}, {constants.CONFIG_INSTALL_PATH: '/tmp'})
        self.conduit.get_units.return_value = []

        report = self.distributor.publish_repo(self.repo, self.conduit, config)

        self.assertTrue(report.success_flag)
        self.assertEqual(len(report.details['errors']), 0)
        self.assertEqual(len(report.details['success_unit_keys']), 0)

        # we still need to clear the destination
        mock_clear.assert_called_once_with('/tmp')

    def _add_error(self, *args, **kwargs):
        """
        add an error to the detail report. This gives us a chance to add an error
        during a particular step in the workflow.
        """
        if not self.distributor.detail_report.report['errors']:
            self.distributor.detail_report.error(self.uk1, 'failed')


class TestCheckForUnsafeArchivePaths(unittest.TestCase):
    def setUp(self):
        self.distributor = installdistributor.PuppetModuleInstallDistributor()
        self.uk1 = {'author': 'puppetlabs', 'name': 'stdlib', 'version': '1.2.0'}
        self.uk2 = {'author': 'puppetlabs', 'name': 'stdlib', 'version': '1.2.1'}
        self.units = [
            AssociatedUnit(constants.TYPE_PUPPET_MODULE, self.uk1, {}, '/a/b/x', '', '', '', ''),
            AssociatedUnit(constants.TYPE_PUPPET_MODULE, self.uk2, {}, '/a/b/y', '', '', '', ''),
        ]

    def test_does_not_exist(self):
        self.distributor._check_for_unsafe_archive_paths(self.units, '/foo/bar')

        self.assertEqual(len(self.distributor.detail_report.report['errors']), 2)
        self.assertTrue(self.distributor.detail_report.report['errors'][0][0] in [self.uk1, self.uk2])
        self.assertTrue(isinstance(self.distributor.detail_report.report['errors'][0][1], basestring))
        self.assertTrue(self.distributor.detail_report.report['errors'][1][0] in [self.uk1, self.uk2])
        self.assertTrue(isinstance(self.distributor.detail_report.report['errors'][1][1], basestring))

    @mock.patch('tarfile.open', autospec=True)
    @mock.patch.object(installdistributor.PuppetModuleInstallDistributor, '_archive_paths_are_safe')
    def test_safe(self, mock_archive_paths_are_safe, mock_open):
        mock_archive_paths_are_safe.return_value = True

        self.distributor._check_for_unsafe_archive_paths(self.units, '/foo/bar')

        mock_archive_paths_are_safe.assert_any_call('/foo/bar', mock_open.return_value)
        self.assertEqual(mock_archive_paths_are_safe.call_count, 2)
        self.assertEqual(len(self.distributor.detail_report.report['errors']), 0)

    @mock.patch('tarfile.open', autospec=True)
    @mock.patch.object(installdistributor.PuppetModuleInstallDistributor, '_archive_paths_are_safe')
    def test_unsafe(self, mock_archive_paths_are_safe, mock_open):
        mock_archive_paths_are_safe.return_value = False

        self.distributor._check_for_unsafe_archive_paths(self.units, '/foo/bar')

        mock_archive_paths_are_safe.assert_any_call('/foo/bar', mock_open.return_value)
        self.assertEqual(mock_archive_paths_are_safe.call_count, 2)
        self.assertEqual(len(self.distributor.detail_report.report['errors']), 2)

        self.assertEqual(mock_open.call_count, 2)
        mock_open.assert_any_call('/a/b/x')
        mock_open.assert_any_call('/a/b/y')


class TestArchivePathsAreSafe(unittest.TestCase):
    def setUp(self):
        self.tarball = tarfile.TarFile(fileobj=StringIO(), mode='w')
        self.tarball.getnames = mock.MagicMock(spec_set=self.tarball.getnames)

    def test_safe_names(self):
        self.tarball.getnames.return_value = [
            'a/b/c',
            'd/e/f',
            'g/h/../i',
        ]

        ret = installdistributor.PuppetModuleInstallDistributor._archive_paths_are_safe(
            '/foo', self.tarball)

        self.assertTrue(ret)

    def test_unsafe_relative_name(self):
        self.tarball.getnames.return_value = [
            'a/b/c',
            'd/e/f',
            '../i',
        ]

        ret = installdistributor.PuppetModuleInstallDistributor._archive_paths_are_safe(
            '/foo', self.tarball)

        self.assertFalse(ret)

    def test_unsafe_absolute_name(self):
        """
        I'm not actually sure if this is possible with a tarball
        """
        self.tarball.getnames.return_value = [
            'a/b/c',
            'd/e/f',
            '/i',
        ]

        ret = installdistributor.PuppetModuleInstallDistributor._archive_paths_are_safe(
            '/foo', self.tarball)

        self.assertFalse(ret)


class TestClearDestinationDirectory(unittest.TestCase):
    def setUp(self):
        self.distributor = installdistributor.PuppetModuleInstallDistributor()

    @mock.patch('shutil.rmtree', autospec=True)
    def test_real_dir(self, mock_rmtree):
        destination = os.path.dirname(os.path.dirname(__file__))

        self.distributor._clear_destination_directory(destination)

        # makes sure it only tries to remove the directories, and not any of the
        # regular files that appear within "destination"
        self.assertEqual(mock_rmtree.call_count, 3)
        mock_rmtree.assert_any_call(os.path.join(destination, 'data'))
        mock_rmtree.assert_any_call(os.path.join(destination, 'integration'))
        mock_rmtree.assert_any_call(os.path.join(destination, 'unit'))


class TestDetailReport(unittest.TestCase):
    def setUp(self):
        self.report = installdistributor.DetailReport()
        self.uk1 = {'author': 'puppetlabs', 'name': 'stdlib', 'version': '1.2.0'}
        self.uk2 = {'author': 'puppetlabs', 'name': 'stdlib', 'version': '1.2.1'}

    def test_success(self):
        self.report.success(self.uk1)

        self.assertTrue(self.uk1 in self.report.report['success_unit_keys'])

    def test_error(self):
        self.report.error(self.uk1, 'failed')

        self.assertTrue((self.uk1, 'failed') in self.report.report['errors'])

    def test_has_errors_true(self):
        self.report.error(self.uk1, 'failed')

        self.assertTrue(self.report.has_errors)

    def test_has_errors_false_success(self):
        self.report.success(self.uk1)

        self.assertFalse(self.report.has_errors)

    def test_has_errors_false_empty(self):
        self.report.success(self.uk1)

        self.assertFalse(self.report.has_errors)

    def test_report_is_dict(self):
        self.assertTrue(isinstance(self.report.report, dict))