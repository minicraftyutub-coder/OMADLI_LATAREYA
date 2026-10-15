# LIVE funksiyasini sozlash

## 1. Render Environment
Render boshqaruv panelida `lotereya-telegram-bot` servisini oching → **Environment**.

Quyidagi o'zgaruvchini qo'shing:

- `LIVE_ADMIN_KEY` — uzun, taxmin qilib bo'lmaydigan maxfiy kalit (kamida 32 ta tasodifiy belgi).
- `PUBLIC_URL` — `https://omadli-latareya.onrender.com`

Saqlang va servisni qayta deploy qiling. `LIVE_ADMIN_KEY` qiymatini ommaga yubormang.

## 2. Admin LIVE ni boshlashi
1. Telegramda botni oching.
2. **⚙️ Operator paneli** → **🎥 Jonli LIVE** tugmasini bosing.
3. Bot yuborgan **Admin kamera sahifasi** havolasini faqat o'zingiz oching.
4. Brauzer kamera va mikrofon ruxsatini so'rasa, ruxsat bering.
5. **🔴 O'yinni boshlash** tugmasini bosing. Bot barcha ro'yxatdan o'tgan foydalanuvchilarga xabar yuboradi; 3 soniyalik sanoqdan so'ng LIVE boshlanadi.
6. **🔄 Kamerani almashtirish** old va orqa kamerani almashtiradi.
7. **⛔ O'yinni tugatish** efirni yopadi. Admin panelidagi LIVE tugatish ham ishlaydi.

## 3. Tomoshabinlar
Tomoshabinlar bot yuborgan `/live` havolasini ochib videoni ko'rishi, izoh yozishi mumkin. Izohlar sahifani ochgan barcha tomoshabinlarga ko'rinadi. Admin sahifasida tomoshabinlar soni ko'rsatiladi.

## Muhim
- Kamera/mikrofon uchun HTTPS va foydalanuvchining brauzer ruxsati kerak.
- WebRTC video uchun STUN serverlari sozlangan; ayrim mobil tarmoqlar yoki qat'iy NAT/firewall holatlarida TURN server kerak bo'lishi mumkin.
- Ushbu versiyada chat tarixi va tomoshabinlar ro'yxati jarayon xotirasida saqlanadi; servis qayta ishga tushsa, ular tozalanadi.
- LIVE video brauzerlar orasida WebRTC orqali uzatiladi. Har bir qo'shimcha tomoshabin adminning internetdan chiqish trafikini oshiradi.
