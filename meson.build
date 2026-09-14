project('hazelux',
  version: '0.1.1',
  meson_version: '>= 0.62.0'
)

python = import('python')
py_installation = python.find_installation('python3')

prefix = get_option('prefix')
bindir = prefix / get_option('bindir')
datadir = prefix / get_option('datadir')
pkgdatadir = datadir / 'hazelux'

# Install python sources
install_subdir('hazelux', install_dir: py_installation.get_install_dir())

# Install desktop file
install_data(
  'data/io.github.hazelux.Hazelux.desktop',
  install_dir: datadir / 'applications'
)

# Install AppStream metainfo
install_data(
  'data/io.github.hazelux.Hazelux.metainfo.xml',
  install_dir: datadir / 'metainfo'
)

# Install scalable icon
install_data(
  'data/icons/hicolor/scalable/apps/io.github.hazelux.Hazelux.svg',
  install_dir: datadir / 'icons/hicolor/scalable/apps'
)

# Install launcher script into bindir
install_data(
  'bin/hazelux',
  install_dir: bindir,
  install_mode: 'rwxr-xr-x'
)
