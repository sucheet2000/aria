package memory

import (
	"fmt"
	"sync"
	"testing"
)

func TestPush_AddsEntries(t *testing.T) {
	wm := New(5)
	wm.Push("alpha")
	wm.Push("beta")

	all := wm.All()
	if len(all) != 2 {
		t.Fatalf("expected 2 entries, got %d", len(all))
	}
	if all[0] != "alpha" || all[1] != "beta" {
		t.Errorf("unexpected entries: %v", all)
	}
}

func TestPush_RespectsMaxSize(t *testing.T) {
	wm := New(3)
	wm.Push("a")
	wm.Push("b")
	wm.Push("c")
	wm.Push("d") // "a" should be evicted

	all := wm.All()
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
		wm.Push(fmt.Sprintf("entry-%d", i))
	}

	last3 := wm.Last(3)
	if len(last3) != 3 {
		t.Fatalf("expected 3 entries, got %d", len(last3))
	}
	if last3[0] != "entry-4" || last3[2] != "entry-6" {
		t.Errorf("unexpected last-3 entries: %v", last3)
	}
}

func TestLast_ReturnsAllWhenFewerThanN(t *testing.T) {
	wm := New(10)
	wm.Push("only")

	result := wm.Last(5)
	if len(result) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(result))
	}
	if result[0] != "only" {
		t.Errorf("unexpected entry: %q", result[0])
	}
}

func TestLast_ReturnsCopy(t *testing.T) {
	wm := New(5)
	wm.Push("original")

	result := wm.Last(1)
	result[0] = "mutated"

	all := wm.All()
	if all[0] != "original" {
		t.Error("Last must return a copy — internal buffer was mutated via returned slice")
	}
}

func TestAll_ReturnsCopy(t *testing.T) {
	wm := New(5)
	wm.Push("original")

	all := wm.All()
	all[0] = "mutated"

	check := wm.All()
	if check[0] != "original" {
		t.Error("All must return a copy — internal buffer was mutated via returned slice")
	}
}

func TestClear_EmptiesBuffer(t *testing.T) {
	wm := New(5)
	wm.Push("a")
	wm.Push("b")
	wm.Clear()

	all := wm.All()
	if len(all) != 0 {
		t.Fatalf("expected empty buffer after Clear, got %d entries", len(all))
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
			for j := 0; j < pushesPerRoutine; j++ {
				wm.Push(fmt.Sprintf("writer-%d-%d", id, j))
			}
		}(i)

		go func() {
			defer wg.Done()
			for j := 0; j < pushesPerRoutine; j++ {
				_ = wm.Last(5)
			}
		}()
	}

	wg.Wait()

	all := wm.All()
	if len(all) > 10 {
		t.Errorf("buffer exceeded maxSize after concurrent writes: len=%d", len(all))
	}
}
