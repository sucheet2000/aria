package memory

import (
	"fmt"
	"sync"
	"testing"
)

const testOwner = "owner_a"

func TestPush_AddsEntries(t *testing.T) {
	wm := New(5)
	wm.Push(testOwner, "alpha")
	wm.Push(testOwner, "beta")

	all := wm.All(testOwner)
	if len(all) != 2 {
		t.Fatalf("expected 2 entries, got %d", len(all))
	}
	if all[0] != "alpha" || all[1] != "beta" {
		t.Errorf("unexpected entries: %v", all)
	}
}

func TestPush_RespectsMaxSize(t *testing.T) {
	wm := New(3)
	wm.Push(testOwner, "a")
	wm.Push(testOwner, "b")
	wm.Push(testOwner, "c")
	wm.Push(testOwner, "d") // "a" should be evicted

	all := wm.All(testOwner)
	if len(all) != 3 {
		t.Fatalf("expected 3 entries after overflow, got %d", len(all))
	}
	if all[0] != "b" {
		t.Errorf("expected oldest surviving entry to be 'b', got %q", all[0])
	}
	if all[2] != "d" {
		t.Errorf("expected newest entry to be 'd', got %q", all[2])
	}
}

func TestLast_ReturnsCorrectCount(t *testing.T) {
	wm := New(10)
	for i := 0; i < 7; i++ {
		wm.Push(testOwner, fmt.Sprintf("entry-%d", i))
	}

	last3 := wm.Last(testOwner, 3)
	if len(last3) != 3 {
		t.Fatalf("expected 3 entries, got %d", len(last3))
	}
	if last3[0] != "entry-4" || last3[2] != "entry-6" {
		t.Errorf("unexpected last-3 entries: %v", last3)
	}
}

func TestLast_ReturnsAllWhenFewerThanN(t *testing.T) {
	wm := New(10)
	wm.Push(testOwner, "only")

	result := wm.Last(testOwner, 5)
	if len(result) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(result))
	}
	if result[0] != "only" {
		t.Errorf("unexpected entry: %q", result[0])
	}
}

func TestLast_ReturnsCopy(t *testing.T) {
	wm := New(5)
	wm.Push(testOwner, "original")

	result := wm.Last(testOwner, 1)
	result[0] = "mutated"

	all := wm.All(testOwner)
	if all[0] != "original" {
		t.Error("Last must return a copy — internal buffer was mutated via returned slice")
	}
}

func TestAll_ReturnsCopy(t *testing.T) {
	wm := New(5)
	wm.Push(testOwner, "original")

	all := wm.All(testOwner)
	all[0] = "mutated"

	check := wm.All(testOwner)
	if check[0] != "original" {
		t.Error("All must return a copy — internal buffer was mutated via returned slice")
	}
}

func TestClear_EmptiesBuffer(t *testing.T) {
	wm := New(5)
	wm.Push(testOwner, "a")
	wm.Push(testOwner, "b")
	wm.Clear(testOwner)

	all := wm.All(testOwner)
	if len(all) != 0 {
		t.Fatalf("expected empty buffer after Clear, got %d entries", len(all))
	}
}

func TestOwnerIsolation_Push(t *testing.T) {
	wm := New(5)
	wm.Push("owner_a", "a-entry")
	wm.Push("owner_b", "b-entry")

	aEntries := wm.All("owner_a")
	if len(aEntries) != 1 || aEntries[0] != "a-entry" {
		t.Errorf("owner_a entries = %v, want [a-entry]", aEntries)
	}

	bEntries := wm.All("owner_b")
	if len(bEntries) != 1 || bEntries[0] != "b-entry" {
		t.Errorf("owner_b entries = %v, want [b-entry]", bEntries)
	}
}

func TestOwnerIsolation_LastAndClear(t *testing.T) {
	wm := New(5)
	wm.Push("owner_a", "a1")
	wm.Push("owner_a", "a2")
	wm.Push("owner_b", "b1")

	if got := wm.Last("owner_a", 5); len(got) != 2 {
		t.Errorf("owner_a Last = %v, want 2 entries", got)
	}

	// Clearing one owner must not affect the other.
	wm.Clear("owner_a")
	if got := wm.All("owner_a"); len(got) != 0 {
		t.Errorf("owner_a after Clear = %v, want empty", got)
	}
	if got := wm.All("owner_b"); len(got) != 1 || got[0] != "b1" {
		t.Errorf("owner_b after clearing owner_a = %v, want [b1]", got)
	}
}

func TestAll_UnknownOwnerReturnsEmpty(t *testing.T) {
	wm := New(5)
	wm.Push("owner_a", "a")
	if got := wm.All("owner_unknown"); len(got) != 0 {
		t.Errorf("unknown owner All = %v, want empty", got)
	}
}

func TestConcurrentPushAndLast(t *testing.T) {
	wm := New(10)
	const goroutines = 20
	const pushesPerRoutine = 50

	var wg sync.WaitGroup
	wg.Add(goroutines * 2)

	for i := 0; i < goroutines; i++ {
		go func(id int) {
			defer wg.Done()
			owner := fmt.Sprintf("owner-%d", id%3)
			for j := 0; j < pushesPerRoutine; j++ {
				wm.Push(owner, fmt.Sprintf("writer-%d-%d", id, j))
			}
		}(i)

		go func(id int) {
			defer wg.Done()
			owner := fmt.Sprintf("owner-%d", id%3)
			for j := 0; j < pushesPerRoutine; j++ {
				_ = wm.Last(owner, 5)
			}
		}(i)
	}

	wg.Wait()

	for i := 0; i < 3; i++ {
		owner := fmt.Sprintf("owner-%d", i)
		if all := wm.All(owner); len(all) > 10 {
			t.Errorf("buffer for %s exceeded maxSize after concurrent writes: len=%d", owner, len(all))
		}
	}
}

// Generation lets a caller detect that Clear ran while it was busy, so a
// late Push after a delete can be dropped.
func TestWorkingMemory_GenerationBumpsOnClearOnly(t *testing.T) {
	wm := New(5)
	g0 := wm.Generation("a")
	wm.Push("a", "x")
	if wm.Generation("a") != g0 {
		t.Fatal("Push must not change the generation")
	}
	wm.Clear("a")
	if wm.Generation("a") == g0 {
		t.Fatal("Clear must bump the generation")
	}
	if wm.Generation("b") != 0 {
		t.Fatal("other owners unaffected")
	}
}

// PushIfGeneration is the atomic check-and-push a cognition turn needs: the
// generation comparison and the append happen under one lock, so a Clear
// cannot slip between them.
func TestWorkingMemory_PushIfGeneration(t *testing.T) {
	wm := New(5)
	gen := wm.Generation("a")
	if !wm.PushIfGeneration("a", "fresh", gen) {
		t.Fatal("push with the current generation must succeed")
	}
	wm.Clear("a")
	if wm.PushIfGeneration("a", "stale", gen) {
		t.Fatal("push with a pre-clear generation must be refused")
	}
	if got := wm.All("a"); len(got) != 0 {
		t.Fatalf("stale inference landed after Clear: %v", got)
	}
	if !wm.PushIfGeneration("a", "after", wm.Generation("a")) {
		t.Fatal("push with the post-clear generation must succeed")
	}
}
