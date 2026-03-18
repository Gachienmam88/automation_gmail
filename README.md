# Gmail Automation Tool

Tool tu dong quan ly tai khoan Gmail hang loat: login, doi mat khau, them email/phone khoi phuc, cai dat 2FA.

## Tinh nang

- **Login hang loat** - Dang nhap nhieu tai khoan Gmail cung luc
- **Doi mat khau** - Tu dong doi password cho nhieu tai khoan
- **Recovery Email/Phone** - Them/doi email va so dien thoai khoi phuc
- **2FA Setup** - Cai dat xac thuc 2 buoc (TOTP)
- **Full Setup** - Thuc hien tat ca cac buoc tren trong 1 lan chay
- **Google Sheets Sync** - Dong bo du lieu voi Google Sheets
- **Excel Export** - Xuat ket qua ra file Excel

## Yeu cau he thong

- Windows 10/11
- Python 3.10+
- Firefox Portable Nightly (tai rieng)
- GeckoDriver v0.36+ (tai rieng)

## Cai dat

### 1. Clone repo

```bash
git clone https://github.com/Gachienmam88/automation_gmail.git
cd automation_gmail
```

### 2. Cai dat dependencies

```bash
pip install -r requirements.txt
```

### 3. Tai Firefox Portable Nightly

Tai tu: https://portableapps.com/apps/internet/firefox-portable-nightly

Giai nen vao thu muc du an:

```
automation_gmail/
  FirefoxPortableNightly/
    App/
      Firefox64/
        firefox.exe    <-- Can file nay
```

### 4. Tai GeckoDriver

Tai tu: https://github.com/mozilla/geckodriver/releases

Chon phien ban phu hop (v0.36+), tai file Windows 64-bit.

Dat file `geckodriver_new.exe` vao thu muc goc du an:

```
automation_gmail/
  geckodriver_new.exe    <-- Dat o day
```

### 5. Chay app

```bash
python main.py
```

## Cau truc du an

```
automation_gmail/
├── main.py                 # Entry point
├── config.py               # Cau hinh chung
├── data.json               # Du lieu tai khoan
├── requirements.txt        # Python dependencies
├── settings.json           # Cai dat nguoi dung
│
├── core/
│   ├── engine.py           # Automation engine (Firefox + Selenium)
│   └── gmail_actions.py    # Logic login, doi pass, recovery, 2FA
│
├── ui/
│   ├── app.py              # Giao dien chinh (Tkinter)
│   ├── grid_view.py        # Bang du lieu 15 cot
│   └── dialogs.py          # Cua so Settings, Sheet Sync
│
├── profile/
│   └── firefox_manager.py  # Quan ly Firefox profiles
│
├── security/
│   └── two_factor.py       # Xu ly 2FA (TOTP + 2fa.live)
│
├── cloud/
│   ├── google_sheets.py    # Dong bo Google Sheets
│   └── google_drive.py     # Upload Google Drive + Excel export
│
├── network/                # (reserved)
│
├── FirefoxPortableNightly/ # Firefox binary (tai rieng, khong commit)
├── firefox_profiles/       # Profiles nguoi dung (tu tao, khong commit)
└── geckodriver_new.exe     # GeckoDriver (tai rieng, khong commit)
```

## Huong dan su dung

1. Chay `python main.py` de mo giao dien
2. Nhap thong tin Gmail vao bang (hoac import tu Google Sheets)
3. Chon action (Login, Change Password, Full Setup, ...)
4. Chon so threads
5. Bam **START**

## Luu y

- Moi Gmail se duoc tao 1 Firefox profile rieng (luu trong `firefox_profiles/`)
- Trinh duyet se **giu mo** sau khi task hoan thanh de kiem tra ket qua
- Bam **STOP** de dong tat ca trinh duyet
- Du lieu duoc luu tu dong vao `data.json`
