# GolfCourse API (`golfcourseapi`) — course and hole reference

**2 tools · BYO key · shapes unverified**

30,000+ courses with per-hole data, from
[golfcourseapi.com](https://golfcourseapi.com).

## Why it complements `datagolf`

`datagolf` gives you tournaments, fields, live models and betting markets. It does not
give you the **course**. This does: every tee box with per-hole par, yardage and stroke
index. That is the layer underneath a course-fit question, or "how has this player
scored on par 3s over 200 yards".

## Auth uses "Key", not "Bearer"

```
Authorization: Key <your key>
```

The literal word `Key`. Using `Bearer` out of habit fails, and the API's 401 does not
say why. This server adds the right prefix — set the bare key:

```bash
export GOLFCOURSE_API_KEY=your_key_here
```

## Tools

| Tool | What it gives you |
|---|---|
| `golfcourseapi_search` | Find a course by name or club — returns the summary only |
| `golfcourseapi_course` | One course in full, with every tee box and all 18 holes |

## The course object is three levels deep

```
course.tees
  ├─ male   → [ {tee_name, course_rating, slope_rating, holes: [ {par, yardage, handicap} × 18 ]} ]
  └─ female → [ ... ]
```

Tee sets are split by **male/female**, each is a **list** of tee boxes, and each tee box
has its own hole array. Three levels before you reach a par.

Note that `handicap` on a hole is its **stroke index** (1 = hardest hole), not a player
handicap.

## Reading a tee box

A single tee box carries everything you need to reason about difficulty:

```json
{"tee_name": "Blue", "course_rating": 74.2, "slope_rating": 144,
 "par_total": 72, "total_yards": 6828, "number_of_holes": 18,
 "holes": [{"par": 4, "yardage": 380, "handicap": 7}, ...]}
```

- **`course_rating`** — the score a scratch golfer is expected to shoot. Above par means
  the course plays hard.
- **`slope_rating`** — how much harder it gets for a bogey golfer. 113 is average; 144 is
  brutal.
- **`handicap`** on a hole is its **stroke index**: 1 is the hardest hole on the course,
  18 the easiest. It is not a player handicap, and this is the field people misread.

## Search before you fetch

`golfcourseapi_search` returns summaries only — id, club, course, location. Per-hole data
needs a second call to `golfcourseapi_course` with the id. Search is the cheap call; use
it to disambiguate first, because club names repeat (there are many "Royal" and
"Riverside" courses).

## Worked example: does this course suit this player?

1. `golfcourseapi_search` → the course id.
2. `golfcourseapi_course` → par and yardage for all 18, plus slope.
3. Count the par 3s over 200 yards, and the par 5s reachable in two.
4. `datagolf` player skill decompositions → whether the field's long hitters or its
   approach players are favoured.

That question is unanswerable with `datagolf` alone, which is the reason this provider
exists here.

## Limits

Coverage is broad (30,000+ courses) but crowd-sourced in places — a small municipal
course may have par and yardage without ratings. Check for `course_rating` before relying
on it.

## See also

- [DataGolf.md](DataGolf.md) — tournaments, fields, models, markets
