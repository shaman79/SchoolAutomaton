# Revize: soulad s českým kurikulem a použitelnost pro děti a rodiče

*Září 2026 · větev `claude/hopeful-cori-o8h953`*

## Shrnutí

Aplikace měla pro Česko dobrý základ: české rozhraní, profil vzdělávacího systému `cs-CZ`,
kurikulární pokyny mimo cachovaný prompt, české krizové linky, anonymní profily bez osobních údajů
a pedagogiku postavenou na růstovém myšlení. **Sladění s českými pravidly ale bylo jen povrchní.**
Pokyn pro model zněl pouze „český RVP“ a americká ročníková pásma se na české stupně mapovala
nepřesně. Nejvýrazněji to bylo vidět u 9. třídy, kterou aplikace sloučila se střední školou.
Přesný ročník se ze zadání ztrácel. Chyběla česká školní notace a terminologie. Rozhraní
ukazovalo „Language Arts · G3-5“ a několik textů bylo jen v mužském rodě. Opakování podle
algoritmu FSRS se plánovalo, ale v aplikaci pro něj nebyla žádná obrazovka.

Větev většinu těchto nálezů opravuje (kapitola 4). Kapitola 5 obsahuje seřazená doporučení na
další práci.

---

## 1. Co funguje dobře

- **Oddělené rozhraní a vzdělávací systém.** Volba `Čeština` nastaví české UI i profil `cs-CZ`.
  Kurikulární pokyn jde do volatilní části promptu, takže cachovaný pedagogický prefix zůstává
  bajtově shodný. Hlídá to test `test_cached_system_prefix_is_unaffected_by_locale`.
- **Bezpečnost dětí.** Jednosměrný tok dat, sanitizace, krizové směrování na Linku bezpečí
  (116 111) a Linku první psychické pomoci (116 123). Model nikdy nepodává „AI poradenství“.
- **Ochrana soukromí.** Nevyžaduje se registrace, e-mail ani jméno, kód se ukládá jen jako hash.
  V Česku je hranice pro souhlas dítěte se zpracováním údajů v online službách 15 let
  (zákon č. 110/2019 Sb.), takže anonymní režim je správná volba.
- **Pedagogika.** Pevná kostra lekce (aktivizace, výklad, řešené a postupně zjednodušované
  příklady, procvičování, prokládané opakování, miskoncepce), spaced repetition FSRS, zpětná vazba
  typu „ještě ne“, žádné žebříčky ve výchozím stavu. To odpovídá formativnímu hodnocení, ke kterému
  MŠMT české školy vede.
- **Přístupnost.** Písmo a motiv pro dyslektiky, omezení pohybu, ovládací prvky ≥ 44 px a význam
  nikdy nenese jen barva.

## 2. Nálezy: soulad s RVP

| # | Nález | Dopad | Stav |
|---|-------|-------|------|
| 1 | Pokyn pro model uváděl jen „český RVP“ bez rozlišení stupně (RVP PV / RVP ZV / RVP G a RVP oborů SOŠ). | Model neví, podle kterého programu obsah stavět. | ✅ opraveno |
| 2 | Pásmo G6-8 odpovídalo „6.–8. ročníku 2. stupně“, jenže 2. stupeň ZŠ je 6.–9. třída. 9. třída spadla do pásma G9-12 spolu se SŠ. | Deváťák, který se chystá na přijímačky podle RVP ZV, mohl dostávat obsah ve stylu střední školy nebo maturity. | ✅ opraveno (přesný ročník + oprava názvů pásem) |
| 3 | Americká pásma G1-2 a G3-5 nekopírují období RVP ZV (1.–3. a 4.–5. třída). | Pro 3. třídu mohl model míchat výstupy 1. a 2. období. | ✅ opraveno (přesný ročník nese i období) |
| 4 | Přesný ročník se ztrácel („pro 4. třídu“ → G3-5), takže model musel hádat v rozsahu tří let. | Obsah mimo úroveň dítěte. | ✅ opraveno: `school_year`, klasifikátor rozumí i výrazům „páťák“, „2. ročník SŠ“, prima–oktáva, „přijímačky“, „maturita“ |
| 5 | Chyběla česká školní notace: desetinná čárka, `3 · 4`, `12 : 3`, mezera mezi tisíci, „české uvozovky“. | Dítě vidí zápis jinak než ve škole. Odpověď „12 500“ nešla odeslat. | ✅ opraveno (pokyn + vstup čísla) |
| 6 | Chyběla česká terminologie a názvy předmětů (prvouka, přírodověda, vlastivěda, přírodopis, vyjmenovaná slova, vzory…). | Obsah zní přeloženě. | ✅ opraveno |
| 7 | Chyběly typické české formáty úloh: doplňovačky i/y přímo ve slově, slovní úlohy ve struktuře zápis → výpočet → odpověď. | Procvičování se nepodobá domácím úkolům. | ✅ opraveno (v pokynu) |
| 8 | U cizích jazyků nebyla cílová úroveň SERR (ZŠ míří na A2, druhý cizí jazyk na A1). | Nevhodná náročnost angličtiny. | ✅ opraveno |
| 9 | Aplikace nemá katalog očekávaných výstupů RVP. Model zná RVP jen z trénovacích dat. | Nelze doložit ani zkontrolovat, že lekce odpovídá konkrétnímu výstupu. | ⏭ doporučení P1 |
| 10 | RVP ZV prochází revizí (Strategie 2030+). | Data zastarají. | ⏭ doporučení: verzovat v `curricula.yaml` |
| 11 | Čitelnost češtiny se nevynucuje. FKGL platí jen pro angličtinu a český proxy ukazatel se pouze zapisuje, nikdy nevede k přegenerování. | Texty pro 1.–2. třídu mohou být příliš těžké. | ⏭ doporučení P2 |
| 12 | `profile.age_band` se nikdy nenastavuje, protože frontend ho neposílá. | Mechanismy pro nejmenší (menší denní dávka nových položek, volný den bez ztráty série) jsou mrtvý kód. | ✅ opraveno: odvozuje se z nastavené třídy |

## 3. Nálezy: české jazykové a UX detaily

- **Mužský rod v textech.** „Dokonči…, abys odemkl“, „Přišel jsi…“, „abys mohl“,
  „Nejsi na to sám“, „Připraven/a“, „Rád/a pomůžu“. ✅ Přepsáno neutrálně.
- **Chybné tvary množného čísla.** „1 dní v řadě“, „2 dní v řadě“. ✅ Doplněno české pravidlo
  pro vue-i18n (1 den / 2 dny / 5 dní).
- **Angličtina v českém UI.** Předmět se zobrazoval jako „Language Arts“ a úroveň jako „G3-5“.
  Po odmítnutí zadání byla tlačítka s náhradními návrhy anglicky a navíc ve tvaru instrukce
  („Try: '…'“), takže se po klepnutí vložila do pole doslova. ✅ Opraveno.
- **Ukázkové zadání.** Příklady odpovídaly spíš americké škole (španělština, fotosyntéza pro
  5. třídu). ✅ Nahrazeny typickými českými tématy: vyjmenovaná slova, násobilka, zlomky,
  anglická slovíčka, přijímačky. Třídu v nich záměrně neuvádím, jinak by přebila třídu
  nastavenou dítětem.
- **Opakování bez obrazovky.** Aplikace slibuje „vrátíme se k tomu ve správnou chvíli“ a
  zahrádka vědomostí ukazuje „čas zalít“, ale žádná obrazovka nevolala `/review/due`.
  ✅ Doplněno „Zalij svou zahrádku“.
- **Nadpis výsledků.** „Skvělá práce!“ se ukazovala i při 30 % úspěšnosti. ✅ Nadpis se teď řídí
  výsledkem.
- **Názvy odznaků na úzkém displeji.** Dlouhé české názvy („Opylovač napříč obory“) přetékaly přes
  okraj karty. ✅ Zalamují se.
- **Hromada upozornění.** Jedna odpověď, která odemkne víc odznaků, vytvořila stoh upozornění
  přes tlačítko „Další“. ✅ Sloučeno do jednoho upozornění.
- **Zvuk.** Přepínač „Zvuk“ ovládá jen tón po odpovědi. Zvuky pro postup na další úroveň a odznaky
  jsou nezapojené (`__saPlayCue` neexistuje). ⏭ doporučení P2.

## 4. Co tato větev mění

**Backend.**

- `app/data/curricula.yaml`: profil `cs-CZ` s rámcovým programem podle stupně (RVP PV, RVP ZV
  s obdobími, RVP G a RVP oborů + maturita), názvy všech ročníků (předškolák, 1.–9. třída,
  1.–4. ročník SŠ, prima–oktáva), notací, terminologií, formáty úloh a cíli SERR. Profily
  `en-US` a `en-GB` dostaly přesné názvy ročníků.
- `app/llm/prompts/curriculum.py`: výběr rámce podle přesného ročníku, jinak podle pásma, plus
  nové části pokynu. Vše zůstává ve volatilní části promptu.
- `StructuredIntent.school_year` (0–13) extrahuje klasifikátor. Neplatná hodnota znamená
  „neuvedeno“ a klasifikaci neshodí.
- Nastavení třídy (`ProfileSettings.school_year`) se posílá s každým zadáním. Použije se jen
  tehdy, když zadání úroveň neuvádí: **zadání má vždy přednost**. Uplatní se jen na cestě
  „proceed“, nikdy při krizovém směrování nebo odmítnutí.
- Přesný ročník se ukládá k lekcím a kvízům. Aditivní migrace SQLite, takže existující data
  zůstanou.
- Nastavená třída určuje věkové pásmo profilu (`age_band`). Konečně tak platí menší denní dávka
  nových položek pro nejmenší a jejich týdenní volný den bez ztráty série. Volný den je teď
  spodní mez, dřív se kvůli výchozí 0 v nastavení nikdy nepoužil.

**Frontend.**

- Výběr třídy jedním klepnutím na úvodní stránce (seskupený podle stupňů, dá se přeskočit) a
  v Nastavení („Moje třída“).
- Obrazovka `/daily` „Zalij svou zahrádku“: nejvýš 10 otázek na kolo. Karta na úvodní stránce a
  v přehledu pokroku ji ukáže, jen když něco čeká. Rostlinka v zahrádce vědomostí má odkaz
  „Dnešní opakování“.
- Česká množná čísla, neutrální texty, české názvy předmětů a úrovní, české příklady zadání.
- Číselná odpověď přijme „12 500“ i „3,5“. Přehled odpovědí píše čísla česky.
- Česky je i stránka 404. Karta s kódem už čtečce obrazovky neříká doslova „code.value“.

**Nezávislá kontrola kódu** našla šest chyb. Všechny jsou opravené a pokryté testy:
1. Třída zvolená před načtením profilu se při prvním zadání přepsala hodnotou ze serveru.
   Zařízení teď posílá třídu jen tehdy, když ji samo změnilo.
2. Na sdíleném zařízení si další dítě „zdědilo“ třídu předchozího. Po zadání jiného kódu teď
   platí třída nového dítěte.
3. Hodnota `1e400` shodila požadavek chybou 500. Teď se ignoruje.
4. Neplatná hodnota v nastavení tiše smazala uloženou třídu. Teď vrátí chybu 422.
5. Deváťák, který výslovně chtěl úroveň SŠ, dostal obsah pro 9. třídu. Třída už pásmo SŠ
   nezužuje na 9. třídu.
6. Po otevření a zavření výběru třídy se ztrácelo zaměření klávesnice. Teď se přesouvá na
   nadpis karty a zpět na tlačítko.

K tomu tyto drobnosti: tlačítka s návrhy už neuvádějí třídu, upřesňující otázka se na třídu
neptá, když ji dítě nastavilo, britské názvy ročníků sedí, souhrn opakování počítá jen
zodpovězené otázky a opakování si poradí s neplatným kódem.

**Ověření.** Backend 262 testů (+58), frontend typecheck, 49 testů (+30) a produkční build.
Aplikace byla spuštěna a ručně prošla v Chromiu na šířce telefonu: výběr třídy (i klávesnicí),
kolo opakování, drobečky lekce „Matematika · 4. třída · 15 min“ a přehled pokroku.

## 5. Doporučení dalšího rozvoje

### P1: největší přínos

1. **Katalog očekávaných výstupů RVP ZV jako data.** Soubor `app/data/rvp_zv.yaml` s výstupy podle
   předmětu a období (kódy ve tvaru `M-5-1-01`, ověřit proti aktuálnímu znění RVP). Do pokynu
   pro model vložit jen relevantní výstupy a nechat ho cíle lekce na ně odkázat. V lekci pak
   zobrazit štítek „Odpovídá RVP ZV: Matematika, 2. období“. Rodiče i učitelé tím dostanou
   ověřitelnou vazbu na kurikulum.
2. **Předčítání (text-to-speech).** Tlačítko 🔊 u textu lekce a zadání otázky přes Web Speech API
   s hlasem `cs-CZ`, bez dalších nákladů. Prvňáci se teprve učí číst a pomůže to i dětem s dyslexií.
3. **Start bez psaní.** Dlaždice předmětů a pod nimi témata pro zvolenou třídu, například pro
   4. třídu: zlomky, písemné násobení, vyjmenovaná slova, slovní druhy, vlastivěda – kraje ČR.
   Doplnit hlasové zadání 🎤 (SpeechRecognition `cs-CZ`, kde prohlížeč podporuje).
4. **Přehled pro rodiče.** Týdenní souhrn: co dítě dělalo, kolik času, co zvládá a co čeká na
   opakování. Místo procent použít slovní hodnocení („zvládá s jistotou / většinou / potřebuje
   procvičit“), které odpovídá českému formativnímu hodnocení. Přidat odkaz ke sdílení, tisk a
   případně PIN. Data už existují (odpovědi, mastery, XP události).

### P2: zábava a motivace

5. **Využít připravené herní režimy.** Výčet `QuizType` obsahuje `timed_sprint`, `boss_review`,
   `no_hint` a `explain_it`, ale všechny kvízy jsou `standard`. Hodí se například „násobilkový
   sprint“ nebo „boss“ na konci tématu. Časové režimy nabízet jen dobrovolně, úzkostné děti
   mohou stresovat.
6. **Maskot a zvuky.** Průvodce (například sova) s reakcemi místo emoji 🧠 na čekací obrazovce a
   krátké zvuky pro postup a odznaky (respektovat přepínač).
7. **Čekání na vygenerování (30–60 s).** Vyplnit ho aktivitou „Víš, že…?“ nebo rozcvičkovou
   otázkou k tématu.
8. **Samolepky a diplom.** Odznaky pojmout jako samolepky do alba. Po zvládnutí tématu nabídnout
   tisknutelný diplom, který děti i rodiče ocení.
9. **Příprava na přijímačky a maturitu.** Samostatný režim ve formátu jednotné přijímací
   zkoušky: úlohy s uzavřenou i otevřenou odpovědí, přiřazování, čas. Po 5. a 7. třídě pro
   víceletá gymnázia, po 9. třídě pro maturitní obory. Úlohy generovat „ve stylu“, nekopírovat
   testy Cermatu.
10. **Kontrola čitelnosti češtiny.** Kalibrovaný ukazatel (délka věty, víceslabičná slova) a u
    1.–3. třídy přegenerovat, pokud je text příliš těžký.
11. **Upozornění mimo zónu palce.** Na telefonu přesunout upozornění nahoru, aby nekolidovala
    s hlavním tlačítkem dole.

### P3: pravidla a provoz

12. **Zásady ochrany osobních údajů česky** a krátká informace pro rodiče: co se ukládá
    (pseudonymní kód, hash IP adresy, odpovědi), jak dlouho a jak profil smazat. U volitelného
    `display_name` upozornit „nepiš celé jméno“.
13. **AI Act.** Upozornění „generuje AI“ už v aplikaci je. S právníkem ověřit, zda se na
    generované obrázky vztahuje povinnost strojově čitelného označení podle čl. 50.
14. **Krizové kontakty.** Zvážit doplnění Rodičovské linky Linky bezpečí (606 021 021), čísla
    155 a chatu Linky bezpečí. Čísla ověřit, soubor má poznámku „legal review pending“.
15. **Prázdninový režim série.** Pauza série přes prázdniny a nemoc, ať motivace netrestá
    odpočinek.
16. **Volitelně Hejného metoda.** Řada českých škol učí matematiku Hejného metodou. Přepínač
    „Hejného / klasická“ by ovlivnil styl úloh (prostředí jako Krokování, Autobus nebo
    Součtové trojúhelníky).

## 6. Poznámky k údržbě

- `PROMPT_VERSION` jsem nezvyšoval. Předchozí změna kurikulárních pokynů ho také nezměnila a
  jeho zvýšení zneplatní cache obrázků (verze je součástí klíče). Pokud chcete v datech odlišit
  obsah vygenerovaný s novými pokyny, zvyšte ji vědomě.
- Nová pole jsou aditivní a nullable. Staré lekce bez `school_year` se zobrazují podle pásma.
