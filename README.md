# Telegram Lotereya Boti

## Imkoniyatlar
- Ism va telefon bilan ro‘yxatdan o‘tish
- 1–6 xonali chipta raqamini tanlash va band raqamlarni bloklash
- 1 soatlik vaqtinchalik band qilish
- To‘lov chekini yuborish, operator tasdiqlashi/rad etishi
- Mening chiptalarim, adminga matn/rasm yuborish va javob olish
- Operator: narx, karta rekviziti, chipta olishni ochish/yopish, statistika
- Barcha foydalanuvchilarga matn/rasm yuborish
- Joriy o‘yin chiptalarini o‘chirish va yangi o‘yin boshlash

## Windowsda ishga tushirish
1. Python 3.11 yoki 3.12 o‘rnating.
2. Terminalda loyiha papkasiga kiring.
3. `py -m venv .venv`
4. ` .venv\\Scripts\\activate`
5. `pip install -r requirements.txt`
6. `.env.example` faylidan nusxa oling va nusxani `.env` deb nomlang.
7. `.env` ichida `BOT_TOKEN` va `ADMIN_IDS` ni to‘ldiring.
8. `python bot.py`

## Telegram ID olish
Bot ishga tushgach, botga `/id` yuboring. Chiqqan raqamni `.env` ichidagi `ADMIN_IDS` qiymatiga yozing. Bir nechta ID kerak bo‘lsa vergul bilan ajrating.

## Render
1. Fayllarni GitHub repozitoriyiga yuklang.
2. Render’da Blueprint orqali `render.yaml` ni tanlang yoki Python Worker yarating.
3. Build command: `pip install -r requirements.txt`
4. Start command: `python bot.py`
5. Environment Variables ichida `BOT_TOKEN` va `ADMIN_IDS` ni kiriting.
6. Ma’lumotlar saqlanib qolishi uchun Render persistent disk ulang va `DATABASE_PATH` ni shu disk ichidagi yo‘lga sozlang. Oddiy vaqtinchalik diskda SQLite ma’lumotlari deploy paytida yo‘qolishi mumkin.

## Muhim
- QR-kod hozircha karta rekviziti matnini kodlaydi; u bank to‘lovini avtomatik tekshirmaydi. Operator bank ilovasidan tekshirishi kerak.
- 1 soatlik chipta band qilish muddati to‘lov tekshiruviga ham tegishli; vaqt tugagach, operator tasdiqlashdan oldin chipta muddati tugagan bo‘lishi mumkin.
- Pul evaziga lotereya/sovrinli o‘yin boshlashdan oldin O‘zbekistondagi amaldagi qonunlar, ruxsatlar, yosh cheklovlari va to‘lov qoidalarini tekshiring.
- Bu boshlang‘ich loyiha. Ommaga ishga tushirishdan oldin backup, maxfiylik siyosati va xavfsizlik sinovlarini bajaring.
