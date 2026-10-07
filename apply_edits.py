import copy


def split_time(start, end, n):
    if n == 0:
        return []
    step = (end - start) / n
    return [(start + i * step, start + (i + 1) * step) for i in range(n)]


def apply_edits(transcript, edits):
    refined = copy.deepcopy(transcript)
    segments_by_id = {seg["seg_id"]: seg for seg in refined["segments"]}

    accepted = [e for e in edits if e["status"] == "accepted"]
    accepted.sort(key=lambda e: e["start_word"], reverse=True)

    edited_ids = set()

    for edit in accepted:
        seg = segments_by_id[edit["seg_id"]]
        start = edit["start_word"]
        end = edit["end_word"]

        old_words = seg["words"][start:end]
        new_texts = edit["replacement"].split()
        times = split_time(old_words[0]["start"], old_words[-1]["end"], len(new_texts))

        new_words = []
        for text, (t_start, t_end) in zip(new_texts, times):
            new_words.append({
                "w": text,
                "start": round(t_start, 3),
                "end": round(t_end, 3),
                "edit_id": edit["edit_id"],
            })

        seg["words"][start:end] = new_words
        seg.setdefault("edit_ids", []).append(edit["edit_id"])
        edited_ids.add(seg["seg_id"])

    for seg in refined["segments"]:
        if seg["seg_id"] in edited_ids:
            seg["text"] = " ".join(w["w"] for w in seg["words"])

    return refined