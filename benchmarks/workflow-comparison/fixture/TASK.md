# משימת המימוש

ממשו token-bucket rate limiter ללא dependencies בקובץ `src/rate-limiter.mjs` בלבד.

ה־API המחייב:

```js
const limiter = createRateLimiter({ capacity, refillPerSecond, maxKeys });
limiter.allow(key, cost, now); // boolean
limiter.peek(key, now);        // number
limiter.reset(key);            // key מסוים
limiter.reset();               // כל המפתחות
limiter.size;                  // מספר buckets שמורים
```

דרישות:

- ייצאו named export בשם `createRateLimiter`.
- `capacity` ו־`refillPerSecond` חייבים להיות מספרים סופיים וחיוביים. `maxKeys` חייב להיות integer חיובי וברירת המחדל שלו 1000.
- `key` חייב להיות string שאינו ריק. `cost` חייב להיות מספר סופי וחיובי וברירת המחדל שלו 1. `now` חייב להיות מספר סופי וברירת המחדל שלו `Date.now()`.
- bucket חדש מתחיל עם `capacity` tokens. החידוש הוא רציף ושברי: `elapsed / 1000 * refillPerSecond`, עד `capacity`.
- זמן שחוזר לאחור לא מחדש tokens ולא מזיז את שעון ה־bucket לאחור.
- ניסיון שנדחה עדיין מעדכן את זמן החידוש לזמן המונוטוני האחרון.
- כל `allow` או `peek` נחשב שימוש לצורך LRU. כאשר עוברים את `maxKeys`, מפנים את המפתח שהשימוש בו הישן ביותר.
- השתמשו ב־`Map`, לא ב־object שמפתחות משתמש מוזנים לתוכו. אל תיצרו timers או background work.
- `peek` מחזיר מספר ואינו צורך token. הוא יוצר bucket חסר.
- `reset(key)` מוחק bucket אחד; `reset()` מנקה הכול.
- אין לשנות את הבדיקות או `package.json`. הריצו `npm test` לפני סיום.
