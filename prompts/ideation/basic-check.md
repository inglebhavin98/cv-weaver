machine parser
- standard, unambiguous headings: `Work Experience`, `Education`, and `Skills`
- text-based, flattened `.pdf`
- **The Gold Standard Date:** Your system should standardize all user inputs to `MM/YYYY` (e.g., `04/2021 – 08/2023`) or `Month YYYY` (e.g., `April 2021 – August 2023`).
- **The Separator:** Connect start and end dates with an en-dash (`–`) surrounded by spaces. Avoid slashes (`/`) for ranges or words like "to" (`04/2021 to Present`), as this confuses older parsers.
- - **Current Roles:** Use the word "Present" for current roles (e.g., `04/2021 – Present`).
- `City, State` (or `City, Country`).
- - **The Failure Point:** "Smart quotes" (curly quotes like `”`), em-dashes (`—`), and fancy bullet points (like `→` or `✓`) often fail UTF-8 encoding checks. The parser converts them into symbols like `` or `?`. This breaks the surrounding words, making them invisible to search.
- - **The Failure Point:** If an email is placed on the same line as a name, the NER might concatenate them (e.g., mapping the candidate's first name as "John john@email.com"). If a user uses the header "My Journey," the NER fails to recognize it as work history and dumps the entire section into an unsearchable "Miscellaneous" database field.

- ASCII-Only Character Normalization: Before your system exports the final PDF or `.docx`, run a script that sanitizes the text.
	- Convert all smart quotes (`“ ”`) to straight quotes (`" "`).
	- Convert all em-dashes and en-dashes to standard hyphens (`-`).
	- Force all bullet points to be standard unicode bullet circles (`•`) or hyphens (`-`).
- Strict Semantic Headers: 
	- `Work Experience` 
	- `Education`
	- `Skills` (or `Technical Skills`)
	- `Certifications`
- The Proximity and Margin Rule: Because NER models rely on spatial relationships to map data:
	- - Ensure the candidate's Name, Phone Number, and Email are on separate lines, or separated by a pipe (`|`) with spaces on both sides.
	- Never put contact information in the actual Header or Footer metadata fields of a Word document. Most parsers (like Apache Tika) ignore document headers entirely. Keep everything in the main body.
- The Sweet Spot: Research indicates the optimal keyword density for a specific skill is between 25 and 35 occurrences across the entire resume. Below 25, the candidate ranks too low in Boolean searches. Above 35, modern AI parsers flag the resume for keyword stuffing.  
- Your system could add immense value by tracking keyword frequency as the user types, displaying a progress bar that turns green at 25 mentions and red at 36.

human eye

|**Structure Phase**|**Purpose**|**Example**|
|---|---|---|
|**1. Action Verb**|Signals ownership and eliminates passive voice.|_Architected, Spearheaded, Optimized_|
|**2. Core Task**|Details the specific project and embeds keywords.|_...the migration of legacy databases to AWS..._|
|**3. Measurable Result**|Proves impact using numbers, percentages, or scale.|_...reducing query latency by 45%._|


- - **Banned Vocabulary:** Your system should flag and remove personal pronouns (`I`, `me`, `we`) and weak, passive phrasing (`Responsible for`, `Helped with`, `Worked on`). Replace them with high-impact verbs.
- - **Tense Consistency:** Past jobs must use past-tense verbs (e.g., _Developed_). Current jobs should use present-tense verbs (e.g., _Develop_), except when referring to completed projects within that current role.
- - **The Acronym Rule:** To satisfy both exact-match and semantic parsers, always spell out a technical term and include the acronym in parentheses the first time it is used. Example: _Search Engine Optimization (SEO)_ or _Key Performance Indicators (KPIs)_.
- **Contextual Density:** ATS systems penalize "keyword stuffing" (listing 50 skills at the bottom of the page). Keywords must be embedded _inside_ the bullet points to prove the candidate actually applied the skill in a professional setting.