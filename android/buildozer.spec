[app]

# (str) Title of your application
title = StreamScanner

# (str) Package name
package.name = streamscanner

# (str) Package domain (needed for android/ios packaging)
package.domain = org.streamscanner

# (str) Source code where the main.py live
source.dir = .

# (list) Source files to include (let empty to include not the exclusion)
source.include_exts = py,png,json,ttf

# (str) Application version — patched from the android-v* tag by CI
version = 1.0.2

# (list) Application requirements
# kivy: UI | pyjnius: clipboard + PackageInstaller | plyer: clipboard fallback
# arabic-reshaper + python-bidi: Persian text shaping in Kivy
# NOTE: charset-normalizer must stay below 3.5: 3.5.0+ ships android-tagged wheels
# on PyPI and python-for-android then fails with "not a supported wheel on this
# platform" when installing with the HOST pip. (It comes in transitively via
# kivy's python_depends -> requests.) IMPORTANT: use "<=" and NOT "==" here —
# p4a's toolchain strips "==x.y.z" pins from requirements (they only apply to
# recipes), so "==" would silently resolve back to 3.5.x and break the build.
requirements = python3,kivy,pyjnius,plyer,arabic-reshaper,python-bidi,charset-normalizer<=3.4.9

# (str) Supported orientations: landscape, portrait, sensor, all ...
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (list) Android permissions
# INTERNET: GitHub update check + APK download
# REQUEST_INSTALL_PACKAGES: install the downloaded APK via PackageInstaller
android.permissions = android.permission.INTERNET,android.permission.REQUEST_INSTALL_PACKAGES

# (int) Target Android API (33 = Android 13)
android.api = 33

# (bool) Auto-accept Android SDK licenses in CI
android.accept_sdk_license = True

# (int) Minimum Android API
android.minapi = 24

# (str) Android NDK version
android.ndk = 25b

# (int) overrides automatic versionCode computation (used in build.gradle)
# patched from the android-v* tag by CI so in-app updates install cleanly
android.numeric_version = 102

# (list) Android architectures: arm64-v8a covers all modern phones and
# halves the CI build time.
android.archs = arm64-v8a

# (str) Path to the app icon (1024x1024 png)
icon.filename = assets/icon.png

# (str) Android app theme: Dark or Light
android.theme = Dark

[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug)
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1
