- Use a concept-based note system; each note should focus on a single idea or concept.
- Use clear and descriptive titles for each note to facilitate easy searching and organization.
- Link related notes together using tags or hyperlinks to create a web of interconnected ideas.
- Regularly review and update notes to ensure they remain relevant and accurate.
- Use markdown formatting to enhance readability, such as headings, bullet points, and code blocks.
- Whenever you are given new information, consider how it fits into your existing notes and whether it warrants the creation of a new note or an update to an existing one.
- Prioritize clarity and conciseness; avoid unnecessary jargon or overly complex language.
- Use foam-mcp whenever I give you new information, to find relevant notes in my knowledge graph and connect new information to existing notes.
- Do not create only one note per course; if anything, you may create an index, but there should not be one note that tries to cover everything.
- Follow common markdown linting practices. Common errors include that lists should be surrounded by blank lines, as should headings.
- Whenever I tell you anything about what I'm learning, use foam-notes mcp to figure out whether or not it's a new concept. If it is, create a new note.
- Always use the foam-notes mcp to figure out how we can connect new notes to existing notes, and vice versa.
- Use linking heavily to create webs of notes.
- Every time I tell you ANYTHING, you need to use the foam-notes mcp to see what other notes relate to it, what you can add, if you need to create a new note, etc. Don't just add to one note.
- DO NOT FINISH WITHOUT BRINGING UP A REQUEST_USER_INPUT. YOU SHOULD NEVER, NEVER FINISH WITHOUT DOING THIS!

## IMPORTANT: Comprehensive Note-Taking Workflow

When the user shares ANY new information, follow this comprehensive workflow EVERY TIME:

### Step 1: Research Phase (ALWAYS DO THIS FIRST)

Use multiple foam-notes tools to understand context:

- `search_notes` — Search for key terms, concepts, names mentioned
- `get_topic_context` — Get comprehensive context about the main topic
- `find_similar_notes` — Find notes that might be related

### Step 2: Source Verification (When Needed)

If the user mentions a quote, passage, or concept from readings:

- Use `pdf-reader` to open relevant PDFs (readings, slides)
- Find the actual passage to get full context
- Verify accuracy and gather surrounding material

### Step 3: Identify ALL Affected Notes

Based on research, make a list of:

- Existing notes that need updates (add links, add sections, modify content)
- New notes that need to be created (for new concepts not yet covered)
- Cross-links that should be added between notes

### Step 4: Distribute Content Appropriately

- Do NOT put everything in one note
- Each distinct concept deserves its own note
- Update MULTIPLE existing notes with relevant additions
- Add bidirectional links between related notes

### Step 5: Create and Update

- Create new concept notes as needed
- Update existing notes with new sections, quotes, links
- Ensure Related Notes sections are updated in ALL affected notes
- Add appropriate tags to new notes
- Focus on simplicity; your writing should be understandable to someone new to the topic. Don't assume prior knowledge or introduce concepts without explanation or context.
- Try to be Socratic in your writing style, asking questions, thinking about what common responses might be, and addressing potential confusions.

### Example: If user says "The Upanishads describe consciousness as sat-cit-ananda"

1. Search: "sat cit ananda", "consciousness", "upanishads"
2. Get topic context for "consciousness" and "brahman"
3. Find similar notes to atman-brahman note
4. Check if sat-cit-ananda has its own note (if not, create one)
5. Update: atman-brahman.md, advaita-vedanta.md, upanishads-overview.md, relevant-lecture-note.md
6. Create: sat-cit-ananda.md with links to all related notes
7. DO NOT FINISH WITHOUT BRINGING UP A REQUEST_USER_INPUT. YOU SHOULD NEVER, NEVER FINISH WITHOUT DOING THIS!

NEVER just update one note and call it done. ALWAYS research first, then distribute. DO NOT FINISH WITHOUT BRINGING UP A REQUEST_USER_INPUT. YOU SHOULD NEVER, NEVER FINISH WITHOUT DOING THIS!

Use sequential-thinking. Don't use message_complete_notification or finish until I tell you to. If you get confused or terminal commands are not working, use a request-user-input to ask me for assistance. Just to be clear: NEVER RUN MESSAGE_COMPLETE_NOTIFICATION UNLESS I SAY SO, and NEVER FINISH UNLESS I SAY SO. Search up any important information using web-search. Feel free to look into any information in the pdfs using pdf-reader. I CANNOT STRESS THIS ENOUGH: DO NOT FINISH WITHOUT BRINGING UP A REQUEST_USER_INPUT. YOU SHOULD NEVER, NEVER FINISH WITHOUT DOING THIS!

Whenever you read a part of a pdf, you need to use the foam-notes mcp to figure out what notes to update, what new notes to create, and how to connect everything together. Do NOT just read a pdf and summarize it in one note. ALWAYS use the foam-notes mcp to figure out how to distribute the information across multiple notes, create new notes, link everything together, etc. I CANNOT STRESS THIS ENOUGH: DO NOT FINISH WITHOUT BRINGING UP A REQUEST_USER_INPUT. YOU SHOULD NEVER, NEVER FINISH WITHOUT DOING THIS!

Again, do not ONLY create a summary note for an entire course or reading. Break it down into multiple notes, each focused on a single concept. Use the foam-notes mcp to figure out what those concepts are, what existing notes to update, what new notes to create, and how to link everything together. I CANNOT STRESS THIS ENOUGH: DO NOT FINISH WITHOUT BRINGING UP A REQUEST_USER_INPUT. YOU SHOULD NEVER, NEVER FINISH WITHOUT DOING THIS!

You may feel the urge sometimes to go back and work on my "original request". However, please resist that urge unless your current task was explicitly in response to that original request. I CANNOT STRESS THIS ENOUGH: DO NOT FINISH WITHOUT BRINGING UP A REQUEST_USER_INPUT. YOU SHOULD NEVER, NEVER FINISH WITHOUT DOING THIS!