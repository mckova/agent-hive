# משימת המימוש

ממשו token-bucket rate limiter ללא תלויות צד שלישי בקובץ `src/rate_limiter.py` בלבד.

ה־API המחייב:

```python
limiter = create_rate_limiter({
    "capacity": capacity,
    "refill_per_second": refill_per_second,
    "max_keys": max_keys,
})
limiter.allow(key, cost, now)  # bool
limiter.peek(key, now)         # number
limiter.reset(key)             # מפתח מסוים
limiter.reset()                # כל המפתחות
limiter.size                   # מספר buckets שמורים
```

דרישות:

- ייצאו פונקציה בשם `create_rate_limiter`.
- `capacity` ו־`refill_per_second` חייבים להיות מספרים סופיים וחיוביים. `max_keys` חייב להיות integer חיובי וברירת המחדל שלו 1000.
- `key` חייב להיות string שאינו ריק. `cost` חייב להיות מספר סופי וחיובי וברירת המחדל שלו 1. `now` הוא מספר סופי במילישניות; ברירת המחדל היא זמן מונוטוני נוכחי.
- bucket חדש מתחיל עם `capacity` tokens. החידוש רציף ושברי: `elapsed / 1000 * refill_per_second`, עד `capacity`.
- זמן שחוזר לאחור אינו מחדש tokens ואינו מזיז את שעון ה־bucket לאחור.
- ניסיון שנדחה עדיין מעדכן את זמן החידוש לזמן המונוטוני האחרון.
- כל `allow` או `peek` נחשב שימוש לצורך LRU. כאשר עוברים את `max_keys`, מפנים את המפתח שהשימוש בו הישן ביותר.
- השתמשו ב־`collections.OrderedDict` או מבנה בטוח מקביל. אין ליצור timers, threads או background work.
- `peek` אינו צורך token ויוצר bucket חסר.
- `reset(key)` מוחק bucket אחד; `reset()` מנקה הכול.
- אין לשנות את `checks/`. הריצו `python -m unittest discover -s checks -v` לפני סיום.
