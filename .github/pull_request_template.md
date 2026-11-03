## 📌 Description
<!-- Provide a clear, concise summary of the changes introduced in this pull request. -->

## 🔗 Related Issue(s)
<!-- Fixes #(issue number) or Closes #(issue number), if applicable. -->

---

## 🛠️ Type of Change
- [ ] 🐛 **Bug Fix** (non-breaking change which fixes an issue)
- [ ] ✨ **New Feature** (non-breaking change which adds new functionality)
- [ ] 🎮 **Hardware Support** (adding or expanding support for a motherboard / RAM model)
- [ ] 🎨 **UI / UX Polish** (visual improvements, styling, animations)
- [ ] ⚡ **Performance / Reliability** (optimizations, driver sync improvements)
- [ ] 📝 **Documentation** (updates to README, guides, or specifications)

---

## 🧪 Hardware & Environment Tested
- **Motherboard Model**: <!-- e.g. MSI B650M GAMING WIFI (MS-7E30) -->
- **BIOS Version**: <!-- e.g. 1.F2 -->
- **CPU**: <!-- e.g. AMD Ryzen 5 7600 -->
- **Linux Distribution & Kernel**: <!-- e.g. Kali Linux / Ubuntu 24.04 (Kernel 6.10) -->
- **Device Node(s)**: <!-- e.g. /dev/hidraw4 (0db0:0076), /dev/i2c-1 (0x72) -->

---

## 🔍 How Was This Tested?
<!-- Describe the tests and verification steps you ran to verify your changes. -->
- [ ] Verified clean launch: `python3 main.py`
- [ ] Verified case fan lighting on physical `JARGB_V2` headers
- [ ] Verified DDR5 / DDR4 RAM RGB synchronization
- [ ] Verified state persistence (`~/.config/fanlight-controller/state.json`) across app reopen
- [ ] Verified both power ON and power OFF (stealth blackout)

---

## 📷 Screenshots / Demos (if applicable)
<!-- Attach screenshots or GIFs if you modified the UI or added visual effects. -->

---

## ✅ Pull Request Checklist
- [ ] My code follows the project's style guidelines ([CONTRIBUTING.md](CONTRIBUTING.md)).
- [ ] I have performed a self-review of my own code.
- [ ] **Privacy Check**: Verified that no personal home directories (`/home/...`), usernames, or credentials are present.
- [ ] I have commented my code, particularly in complex low-level driver / protocol areas.
- [ ] My changes generate no new warnings or errors.
