Name:           litehub
Version:        0.4.0
Release:        1%{?dist}
Summary:        Lightweight all-in-one messenger hub (WhatsApp, Slack, Discord, Gmail, ...)
License:        MIT
URL:            https://github.com/gbnanoengineer/litehub
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
install -Dm755 src/litehub.py %{buildroot}%{_bindir}/litehub
install -Dm644 packaging/litehub.desktop %{buildroot}%{_datadir}/applications/litehub.desktop
install -Dm644 packaging/litehub.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/litehub.svg
install -Dm644 README.md %{buildroot}%{_docdir}/%{name}/README.md

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/litehub.desktop

%files
%license LICENSE
%doc README.md
%{_bindir}/litehub
%{_datadir}/applications/litehub.desktop
%{_datadir}/icons/hicolor/scalable/apps/litehub.svg

%changelog
* Wed Oct 14 2026 gbnanoengineer <gbnanoengineer@users.noreply.github.com> - 0.4.0-1
- Qt/Chromium engine, multi-account services, themes, shared download manager
