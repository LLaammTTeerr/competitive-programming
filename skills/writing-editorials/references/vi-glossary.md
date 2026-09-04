# Vietnamese glossary for editorials

The canonical gloss for `writing-editorials` when the page is Vietnamese.
Read it before writing, not after — a term chosen on the fly and then
corrected has to be chased through the whole page, and through the contest
copy as well.

This file is the record, so when the user corrects a translation, fix the
row here in the same turn as the HTML. Patching only the page means the
next editorial makes the same mistake.

## Translate for meaning, and keep Vietnamese word order

Do not translate word for word. Write what a Vietnamese olympiad
contestant would actually say. The rule that catches the most drafts is
word order: **compound nouns put the modifier first**, so the English
adjective ends up at the front, not trailing the noun.

| English | Use | Never |
|---|---|---|
| simple graph | **đơn đồ thị** | đồ thị đơn |
| multigraph | **đa đồ thị** | đồ thị đa |

The same shape carries through combinations — đơn đồ thị vô hướng, not
"đồ thị đơn vô hướng".

## Stays in English

These are labels, tags, and names; Vietnamese-izing them makes the page
harder to read, not more Vietnamese. They stay English inside a Vietnamese
sentence.

**Page chrome.** Time limit, Memory limit, Difficulty, Tags, Solution,
Other solutions, Time complexity, Observation, Lemma, Fun fact, the word
Subtask (visible titles are Subtask 1, Subtask 2, …), amortized and
non-amortized. The bar kicker, the `<title>` suffix and the footer read
**Solution** — never "lời giải", never "Editorial".

**Bitwise and algebra tokens.** XOR, AND, OR, NOT, mask, bit, bitmask,
LSB, MSB, popcount, modulo.

**Techniques and structures.** DP, DFS, BFS, DSU, BCC, LCA, RMQ, HLD, MST,
SCC, DAG, FFT, NTT; segment tree, BIT, Fenwick, trie, binary heap, sparse
table, binary lifting, virtual tree, centroid, Euler tour; sort, brute,
greedy, two pointers, binary search; Tarjan, Kruskal, Dijkstra,
Floyd–Warshall, KMP, Z-function; handshake lemma, Sprague–Grundy.

**Graph words that stay English in a writeup**, even though they have
Vietnamese glosses in a textbook: bridge, biconnected component,
2-edge-connected, 2-edge-cut, cut vertex, block. Write "tính bridge bằng
Tarjan DFS", not "tính cầu".

Tag strings keep their Codeforces spelling: `graphs`, `data structures`,
`dp`, `dfs and similar`, …

## Translate

### Statement labels

The order inside the restatement section is fixed: restatement →
**Yêu cầu** → **Giới hạn** → **Subtask**.

| English | Vietnamese |
|---|---|
| the problem (section heading) | Đề bài |
| requirement (last line of the restatement, above the bounds) | Yêu cầu |
| constraints | Giới hạn |
| subtask list label | Subtask |
| points (a subtask's score) | điểm |
| no additional constraints | không ràng buộc thêm |
| subtask summary (table heading) | Tóm tắt subtask |
| insight (table heading) | Ý tưởng |

### Graphs

| English | Vietnamese |
|---|---|
| simple graph | đơn đồ thị |
| multigraph | đa đồ thị |
| undirected graph | đồ thị vô hướng |
| undirected simple graph | đơn đồ thị vô hướng |
| directed graph | đồ thị có hướng |
| weighted graph | đồ thị có trọng số |
| complete graph | đồ thị đầy đủ |
| bipartite graph | đồ thị hai phía |
| vertex / node | đỉnh |
| edge | cạnh |
| loop / self-loop | khuyên |
| parallel edges | cạnh kép |
| adjacent | kề |
| neighborhood | láng giềng |
| connected | liên thông |
| connected component | thành phần liên thông |
| disconnected | không liên thông |
| strongly connected | liên thông mạnh |
| path | đường (đường đi) |
| shortest path | đường đi ngắn nhất |
| cycle | chu trình |
| acyclic | không chu trình |
| degree | bậc |
| even / odd degree | bậc chẵn / bậc lẻ |
| isolated vertex | đỉnh cô lập |
| leaf | lá |
| spanning tree | cây khung |
| matching | cặp ghép |
| cut (as in min-cut) | lát cắt |
| flow | luồng |
| topological order | thứ tự topo |

### Trees

| English | Vietnamese |
|---|---|
| tree | cây |
| forest | rừng |
| rooted tree | cây có gốc |
| root | gốc |
| parent | cha |
| child | con |
| ancestor | tổ tiên |
| descendant | con cháu |
| subtree | cây con |
| depth / layer | độ sâu / lớp |
| height | chiều cao |
| binary tree | cây nhị phân |

### Games and I/O

| English | Vietnamese |
|---|---|
| two players | hai người chơi |
| first / second player | người đi trước / người đi sau |
| turn | lượt |
| optimal play | chơi tối ưu |
| winner / loser | người thắng / người thua |
| winning / losing position | thế thắng / thế thua |
| print | in |
| count | đếm |
| any valid answer | bất kỳ đáp án hợp lệ |
| multiple answers | nhiều đáp án |

### Numbers and combinatorics

| English | Vietnamese |
|---|---|
| even / odd | chẵn / lẻ |
| strictly increase | tăng nghiêm ngặt |
| pairwise | từng cặp |
| permutation | hoán vị |
| combination | tổ hợp |
| subset | tập con |
| prefix / suffix | tiền tố / hậu tố |
| cost | chi phí |
| paint / color (a vertex) | tô màu |
| query | truy vấn (the noun; "query" as a technique stays English) |

Add a row whenever a problem forces you to invent a gloss, and keep one
canonical Vietnamese word per English term — synonym cycling reads as
generated prose, and the skill's Voice section rules it out on the page
for the same reason.
