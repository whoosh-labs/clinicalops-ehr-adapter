# Patient Schedule → Insurance CSV: Instructions for Claude

When this file is uploaded together with a patient schedule export, follow these instructions to produce the CSV. The export can be either of the two input formats below. Don't ask for confirmation first. Run the script below, check the output, deliver the CSV, and report what was dropped and anything that needs review.

## Input formats

The script detects the format from the file extension: `.pdf` is Format A, and `.csv` is Format B. If a file matches neither format (different columns or a different layout), stop and tell the user. Don't guess at the columns.

### Format A: ModMed face sheet PDF (e.g. `vegas-week-of-5th_oc.pdf`)

- There is one page per appointment. Each page shows `Appointment: MM/DD/YYYY H:MM AM` at the top right with `Provider: Last, First` below it.
- The **Patient Information** section has `Name:` (in the order FIRST MIDDLE LAST) and `D.O.B:`.
- There are zero or more insurance blocks, each titled **Primary / Secondary Insurance Information**. Each block has `Carrier:` and `Policy #:`. Long carrier names wrap onto two lines, for example "UMR formerly Commonwealth / Administrators, LLC" and "AARP Medicare Supplement/Fixed / Indemnity by UHC".

### Format B: PatientDemoGraphicData CSV (e.g. `PatientDemoGraphicData_10052026_0913130.csv`)

- There is one row per appointment, and the file has 40 columns. It has **primary insurance only**, so each appointment produces at most one output row.
- Column mapping:

| Output column | Source column | Transform |
|---|---|---|
| patient name | `Pat L Name`, `Pat F Name`, `Pat M Initial` | `Last, First M` (initial included only if present), original casing |
| date of service | `Date` | `2026-10-05` → `10/05/2026` |
| birth date | `Pat Birthdate` | already `mm/dd/yyyy` |
| appointment provider | `ProviderName` | as printed, e.g. `Rivera Ana L`. Do **not** use `ResourceName`, which holds values like OIT or Allergy Shots |
| insurance name | `Primary Insurance Name` | as printed |
| policy number | `Primary Ins Subscriber No` | as printed (not the Group No) |

## Output: CSV with exactly these columns, in this order

```
patient name,date of service,birth date,appointment provider,insurance name,policy number
```

| Column | Format / source |
|---|---|
| patient name | `LAST, FIRST MIDDLE` (see name rules) |
| date of service | `mm/dd/yyyy`, the appointment date |
| birth date | `mm/dd/yyyy`, from D.O.B |
| appointment provider | as printed in the source (Format A: `Rivera, Ana`; Format B: `Rivera Ana L`) |
| insurance name | full carrier name, with wrapped lines joined by a single space |
| policy number | as printed, kept as text (leading zeros preserved) |

**Split into multiple files:** each CSV may have at most **100 lines including the header**, so at most 99 patient rows per file. Every file repeats the header row.
- Fill each file to 99 patient rows, in order, and put whatever is left in the last file. Use the fewest files possible and **do not** split evenly. For example, 298 rows becomes 99/99/99/1.
- An appointment's Primary and Secondary rows always go in the same file. If a pair would land on the 99/100 boundary, that file stops at 98 rows and the pair moves to the next file.
- Name the files `<prefix>_part1.csv`, `<prefix>_part2.csv`, and so on, keeping the source order.

## Rules

1. **Multiple insurances:** each insurance block gets its own row. Name, date of service, DOB and provider are repeated, and only the insurance name and policy number differ. Rows follow the PDF order: Primary first, then Secondary directly below it.
2. **Patients seen more than once in the week** get one row (or set of rows) per appointment page. Don't deduplicate across dates.
3. **Drop incomplete insurance:**
   - If a patient has no insurance block, drop the patient.
   - If an insurance block has a blank carrier or a blank policy number, drop that row.
   - If the carrier is `Payer Not Found`, `CASH PAY`, `Self Pay`, or `None`, drop that row. This also applies when the policy number is a placeholder `0` or `1`.
   - If a patient has one complete and one incomplete block, keep the complete row and drop only the incomplete one.
4. **Keep only real insurance payers. Drop manufacturer copay and patient-support programs.** These programs are not insurance and can't be verified through eligibility (VOB), so they never go in the CSV.
   - Drop any row whose carrier contains `copay`, `co-pay`, `patient assistance`, `assistance program`, or `savings` (case-insensitive). Examples: `Xolair Copay Assistance`, `Tezspire Copay Assistance`, `Dupixent MyWay`, and `Biologic Copay Assistance Program`.
   - Also drop programs named after a biologic even without those words. The script catches Xolair, Tezspire, Dupixent, Nucala, Fasenra and Cinqair; add new drug names to `SUPPORT` as they appear. If you're unsure whether a carrier is a payer or a support program, keep the row and flag it in the summary.
   - Drop only the program row. The patient's real Primary/Secondary insurance rows stay. If the program was the patient's only insurance, the patient is dropped like any other patient with no insurance.
   - Do **not** drop government payers just because their name contains "Assistance". For example, Maryland Medicaid is called "Medical Assistance", and it is a real payer.
   - Report the support-program drops as a count per program in the summary rather than listing every row.
5. **Keep everything else exactly as printed**, including "Testing" providers (e.g. `Lopez, Testing`) and biologic or injection resources used as providers (e.g. `Shot, Biologic`, `K STREET, BIOLOGICS`). Mention them in the summary, but don't remove them.
6. **Name rules (Format A only;** Format B already has separate name fields):
   - Remove titles: Mr, Mrs, Ms, Dr, Miss (with or without a period).
   - The last word is the last name, and everything before it is first plus middle. Keep the original casing. Example: `ANNA Marie COLE` → `COLE, ANNA Marie`.
   - Suffixes (Jr, Sr, II, III, IV) attach to the last name. Example: `PETER James HALL, III` → `HALL III, PETER James`.
   - If the second word is a middle initial, everything after it is the last name. Example: `NORA K BELL TATE` → `BELL TATE, NORA K`.
   - Surname particles stay with the last name (SAN, DE, DEL, LA, LOS, VAN, VON, DA, DI, ST). Examples: `JUAN D SAN MARTIN` → `SAN MARTIN, JUAN D`; `ROSA DE LA CRUZ` → `DE LA CRUZ, ROSA`.
   - Flag possible compound Hispanic surnames for review, but don't change them. Example: `LUCIA MARIA VEGA ROJAS` → `ROJAS, LUCIA MARIA VEGA`.

## How to run

For PDFs, the script needs `pdftotext` (poppler-utils). Save the script below as `facesheet_to_csv.py` and run:

```bash
python3 facesheet_to_csv.py /mnt/user-data/uploads/<input>.pdf|.csv /mnt/user-data/outputs/<input>_patients
```

The second argument is a file prefix, not a filename. The script writes `<prefix>_part1.csv`, `<prefix>_part2.csv`, and so on, and prints the row count for each file, the source page/row count, the total output row count, and every dropped row with its page or line number and reason. Present all the part files to the user.

### Sanity checks before delivering

- The source count printed must match the input: `pdfinfo` Pages for Format A, or the CSV's line count minus 1 for Format B.
- Format B: output rows + dropped rows must equal the source row count.
- Every part file must have 100 lines or fewer, header included (`wc -l`).
- Format A: rows should equal the number of complete insurance blocks across all pages.
- Format A: run `grep -c "Insurance Information"` on the text and compare it to rows + dropped insurance rows (support-program drops included).
- Check that no output row's insurance name is a copay or support program (`grep -i "copay\|assistance" *_part*.csv` should return nothing, except a real payer such as "Medical Assistance").
- If the script errors on a page, or a carrier looks wrong (an address, `Address:`, or cut-off text), rasterize that page (`pdftoppm -jpeg -r 90 -f N -l N`), look at it, and fix the row by hand.
- In the summary, mention any oddities, such as two blocks both labeled Primary, a blank carrier, or "Payer Not Found".

### Script

```python
import re, csv, sys, subprocess
pdf, out = sys.argv[1], sys.argv[2]   # input: face sheet .pdf OR PatientDemoGraphicData .csv   # out = output path prefix, e.g. /mnt/user-data/outputs/vegas_week
MAX_LINES = 100                       # per file, INCLUDING the header row -> max 99 patient rows
def left_val(line):
    # value in the left column: text segment starting between col 15 and 45, not a label
    return " ".join(m.group() for m in re.finditer(r"\S+(?: \S+)*", line)
                    if 15 <= m.start() < 45 and not m.group().endswith(":"))

PRE = {"MR", "MRS", "MS", "DR", "MISS"}
SUF = {"JR", "SR", "II", "III", "IV"}
PART = {"SAN", "DE", "DEL", "LA", "LOS", "VAN", "VON", "DA", "DI", "ST"}
def fmt_name(n):
    t = n.replace(",", " ").split()
    while t and t[0].rstrip(".").upper() in PRE: t = t[1:]
    suf = t.pop() if t and t[-1].rstrip(".").upper() in SUF else ""
    if len(t) >= 3 and len(t[1].rstrip(".")) == 1:      # FIRST M LAST LAST
        first, last = t[:2], t[2:]
    else:
        k = len(t) - 1
        while k > 1 and t[k-1].upper() in PART: k -= 1  # SAN MARTIN, DE LA ...
        first, last = t[:k], t[k:]
    return f"{' '.join(last)}{' ' + suf if suf else ''}, {' '.join(first)}"

NO_INS = {"", "payer not found", "cash pay", "self pay", "self-pay", "selfpay", "none"}
# Manufacturer copay / patient-support programs are NOT insurance payers -> always drop (rule 4)
SUPPORT = re.compile(r"copay|co-pay|patient assistance|assistance program|savings|xolair|tezspire|dupixent|nucala|fasenra|cinqair|myway", re.I)
def is_support(carrier):
    return bool(SUPPORT.search(carrier or ""))
def bad(carrier, policy):
    return not carrier or not policy or carrier.strip().lower() in NO_INS or policy.strip() in {"0", "1"}
def reason(carrier, policy):
    if is_support(carrier): return f"support program, not a payer: carrier='{carrier}'"
    return f"incomplete insurance: carrier='{carrier}' policy='{policy}'"

rows, dropped = [], []
if pdf.lower().endswith(".pdf"):
    # ---------- FORMAT A: ModMed face sheet PDF ----------
    text = subprocess.run(["pdftotext", "-layout", pdf, "-"], capture_output=True, text=True).stdout
    pages = [p for p in text.split("\f") if p.strip()]
    src_count = len(pages)

    for i, p in enumerate(pages, 1):
        L = p.split("\n")
        dos = re.search(r"Appointment:\s*(\d{2}/\d{2}/\d{4})", p).group(1)
        prov = [re.search(r"Provider:\s*(.+)", l).group(1).strip() for l in L[:3] if "Provider:" in l][0]
        name = fmt_name(left_val([l for l in L if l.startswith("Name:")][0]))
        dob = re.search(r"D\.O\.B:\s+(\d{2}/\d{2}/\d{4})", p).group(1)
        base = [name, dos, dob, prov]
        blocks = [k for k, l in enumerate(L) if re.match(r"^\s*(Primary|Secondary|Tertiary) Insurance Information", l)]
        if not blocks:
            dropped.append((i, name, "no insurance on file")); continue
        for k in blocks:
            j, car = k + 1, []
            while j < len(L) and not L[j].startswith("Policy #:"):
                car.append(left_val(L[j].replace("Carrier:", "        ", 1))); j += 1
            carrier = " ".join(c for c in car if c).strip()
            policy = left_val(L[j].replace("Policy #:", "         ", 1)) if j < len(L) else ""
            if is_support(carrier) or bad(carrier, policy):
                dropped.append((i, name, reason(carrier, policy))); continue
            rows.append((i, base + [carrier, policy]))   # i = page, keeps an appointment's rows together


else:
    # ---------- FORMAT B: PatientDemoGraphicData CSV export (one row per appointment, primary insurance only) ----------
    with open(pdf, encoding="utf-8-sig", newline="") as f:
        data = list(csv.DictReader(f))
    src_count = len(data)
    for i, x in enumerate(data, 2):                 # i = line number in the source file
        g = lambda k: (x.get(k) or "").strip()
        first = " ".join(v for v in [g("Pat F Name"), g("Pat M Initial")] if v)
        name = f"{g('Pat L Name')}, {first}"
        y, m, d = g("Date").split("-")              # 2026-10-05 -> 10/05/2026
        dos = f"{m}/{d}/{y}"
        base = [name, dos, g("Pat Birthdate"), g("ProviderName")]   # ProviderName, NOT ResourceName (OIT, Allergy Shots)
        carrier, policy = g("Primary Insurance Name"), g("Primary Ins Subscriber No")
        if is_support(carrier) or bad(carrier, policy):
            dropped.append((i, name, reason(carrier, policy))); continue
        rows.append((i, base + [carrier, policy]))

HEADER = ["patient name", "date of service", "birth date", "appointment provider", "insurance name", "policy number"]
# group rows by appointment page so primary + secondary never get split across files
groups = []
for page, row in rows:
    if groups and groups[-1][0] == page: groups[-1][1].append(row)
    else: groups.append((page, [row]))
# fill each file to 99 patient rows, remainder goes in the last file (fewest files possible)
cap = MAX_LINES - 1
chunks, cur = [], []
for _, g in groups:
    if cur and len(cur) + len(g) > cap:   # a primary+secondary pair never straddles two files
        chunks.append(cur); cur = []
    cur += g
if cur: chunks.append(cur)
for n, chunk in enumerate(chunks, 1):
    path = f"{out}_part{n}.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(HEADER); w.writerows(chunk)
    print(f"{path}: {len(chunk)} patient rows (+ header)")
print(f"source pages/rows={src_count} output rows={len(rows)} dropped={len(dropped)}")
from collections import Counter
prog = Counter(r.split("carrier='")[1].rstrip("'") for _, _, r in dropped if r.startswith("support program"))
for k, v in prog.items(): print(f"SUPPORT PROGRAM DROPPED: {k} x{v}")
for d in dropped:
    if not d[2].startswith("support program"): print("DROPPED (page/line)", *d)
```

## Reply to the user after generating

Keep it short and include:
- the number of files and the row count in each, plus the total
- the number of patients with a secondary insurance
- the support-program rows dropped, as a count per program (e.g. "Xolair Copay Assistance: 55")
- the dropped rows with names and reasons
- names worth double-checking
- this tip: when opening the CSV in Excel, import the policy number column as Text so leading zeros are kept
