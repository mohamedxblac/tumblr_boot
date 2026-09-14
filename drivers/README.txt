Bundled GeckoDriver
===================

Version: 0.37.1 (Windows x64)
Source: https://hg.mozilla.org/mozilla-central/file/tip/testing/geckodriver
License: Mozilla Public License 2.0 (https://mozilla.org/MPL/2.0/)
SHA-256: E95B4EAC7960FFCD5ACBFD92BB7D49D48F99C1D01A20DDD297FEF8C80821020D

PyInstaller embeds drivers/geckodriver.exe in TumblrBot.exe. At runtime the
application passes its extracted path directly to Selenium, so Selenium Manager
does not need network access or a pre-existing driver cache on the RDP host.
