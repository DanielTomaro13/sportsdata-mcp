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

## See also

- [DataGolf.md](DataGolf.md) — tournaments, fields, models, markets
