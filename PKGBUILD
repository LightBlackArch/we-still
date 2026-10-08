# Maintainer: we-still contributors
pkgname=we-still
pkgver=0.1.0
pkgrel=1
pkgdesc='Set a Steam Wallpaper Engine wallpaper as a high-quality still desktop background'
arch=('any')
url='https://github.com/LightBlackArch/we-still'
license=('MIT')
depends=('python' 'python-pillow' 'python-numpy' 'ffmpeg')
optdepends=('waypaper: GUI picker (see "we-still setup")' 'libnotify: desktop notifications')
makedepends=('python-build' 'python-installer' 'python-setuptools' 'python-wheel')
source=("$pkgname-$pkgver.tar.gz")
sha256sums=('SKIP')

build() {
  cd "$pkgname-$pkgver"
  python -m build --wheel --no-isolation
}

package() {
  cd "$pkgname-$pkgver"
  python -m installer --destdir="$pkgdir" dist/*.whl
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
