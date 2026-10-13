Name:           tessera
Version:        0.5.0
Release:        1%{?dist}
Summary:        Lightweight all-in-one messenger hub (WhatsApp, Slack, Discord, Gmail, ...)
License:        MIT
URL:            https://github.com/gbnanoengineer/tessera
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
BuildRequires:  desktop-file-utils
Requires:       python3
Requires:       python3-pyqt6
Requires:       python3-pyqt6-webengine
Requires:       qt6-qtsvg
Requires:       libnotify
Requires:       xdg-utils

%description
One window for many web services, each instance with its own isolated login:
several WhatsApps (linked-device QR login), Gmails, Outlooks, Telegram, Slack,
Discord, Teams, Messenger and custom sites. Chromium (Qt WebEngine) engine with
working calls, video and screen sharing, a shared download manager, tray,
per-app notifications, dark/light theme and custom CSS/JS.
Unofficial; not affiliated with any of these services.

%prep
%autosetup

%install
install -Dm755 src/tessera.py %{buildroot}%{_bindir}/tessera
install -Dm644 packaging/tessera.desktop %{buildroot}%{_datadir}/applications/tessera.desktop
install -Dm644 packaging/tessera.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/tessera.svg
install -Dm644 README.md %{buildroot}%{_docdir}/%{name}/README.md

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/tessera.desktop

%files
%license LICENSE
%doc README.md
%{_bindir}/tessera
%{_datadir}/applications/tessera.desktop
%{_datadir}/icons/hicolor/scalable/apps/tessera.svg

%changelog
* Wed Oct 14 2026 gbnanoengineer <gbnanoengineer@users.noreply.github.com> - 0.5.0-1
- Renamed to Tessera; real brand logos; Qt/Chromium engine, multi-account services, themes
