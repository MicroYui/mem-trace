// Command go-trace-collector is a thin, scale-only trace ingestion gateway for
// MemTrace (ROADMAP §6 / architecture §3.2).
//
// It is intentionally minimal: a high-throughput front door that accepts agent
// trace events over HTTP, batches them, and forwards each to the Python
// MemTrace runtime's `/v1/events` endpoint. The Python runtime remains the
// source of truth and owns all memory/state/gate semantics — this collector
// never interprets events, it only buffers and forwards. It exists for the
// scale scenario where Python ingestion QPS becomes the bottleneck; it is not
// part of the default deployment.
package main

import (
	"bytes"
	"encoding/json"
	"io"
	"log"
	"net/http"
	"os"
	"sync"
	"time"
)

// Config is read from the environment so the collector has no build-time coupling
// to a particular MemTrace deployment.
type Config struct {
	ListenAddr   string        // COLLECTOR_LISTEN_ADDR, default ":8088"
	MemTraceURL  string        // MEMTRACE_BASE_URL, e.g. http://localhost:8000
	APIKey       string        // MEMTRACE_API_KEY (optional bearer)
	FlushEvery   time.Duration // COLLECTOR_FLUSH_MS, default 200ms
	MaxBatchSize int           // COLLECTOR_MAX_BATCH, default 256
}

func loadConfig() Config {
	cfg := Config{
		ListenAddr:   envOr("COLLECTOR_LISTEN_ADDR", ":8088"),
		MemTraceURL:  envOr("MEMTRACE_BASE_URL", "http://localhost:8000"),
		APIKey:       os.Getenv("MEMTRACE_API_KEY"),
		FlushEvery:   200 * time.Millisecond,
		MaxBatchSize: 256,
	}
	return cfg
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// Collector buffers raw event payloads and forwards them to MemTrace.
type Collector struct {
	cfg    Config
	client *http.Client
	mu     sync.Mutex
	buffer [][]byte
}

func NewCollector(cfg Config) *Collector {
	return &Collector{cfg: cfg, client: &http.Client{Timeout: 5 * time.Second}}
}

func (c *Collector) enqueue(payload []byte) {
	c.mu.Lock()
	c.buffer = append(c.buffer, payload)
	c.mu.Unlock()
}

func (c *Collector) drain() [][]byte {
	c.mu.Lock()
	defer c.mu.Unlock()
	batch := c.buffer
	c.buffer = nil
	return batch
}

// forward posts a single event payload to the MemTrace runtime. The collector
// does not transform the payload; it only adds the bearer header when present.
func (c *Collector) forward(payload []byte) {
	req, err := http.NewRequest(http.MethodPost, c.cfg.MemTraceURL+"/v1/events", bytes.NewReader(payload))
	if err != nil {
		log.Printf("collector: build request failed: %v", err)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	if c.cfg.APIKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.cfg.APIKey)
	}
	resp, err := c.client.Do(req)
	if err != nil {
		log.Printf("collector: forward failed: %v", err)
		return
	}
	io.Copy(io.Discard, resp.Body)
	resp.Body.Close()
}

func (c *Collector) flushLoop() {
	ticker := time.NewTicker(c.cfg.FlushEvery)
	defer ticker.Stop()
	for range ticker.C {
		for _, payload := range c.drain() {
			c.forward(payload)
		}
	}
}

func (c *Collector) handleEvent(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	body, err := io.ReadAll(io.LimitReader(r.Body, 1<<20))
	if err != nil {
		http.Error(w, "read error", http.StatusBadRequest)
		return
	}
	// Validate it is JSON, but do not interpret the event.
	if !json.Valid(body) {
		http.Error(w, "invalid json", http.StatusBadRequest)
		return
	}
	c.enqueue(body)
	w.WriteHeader(http.StatusAccepted)
	w.Write([]byte(`{"queued":true}`))
}

func (c *Collector) handleHealth(w http.ResponseWriter, _ *http.Request) {
	w.WriteHeader(http.StatusOK)
	w.Write([]byte(`{"status":"ok"}`))
}

func main() {
	cfg := loadConfig()
	collector := NewCollector(cfg)
	go collector.flushLoop()

	mux := http.NewServeMux()
	mux.HandleFunc("/collect/events", collector.handleEvent)
	mux.HandleFunc("/health", collector.handleHealth)

	log.Printf("go-trace-collector listening on %s -> %s", cfg.ListenAddr, cfg.MemTraceURL)
	if err := http.ListenAndServe(cfg.ListenAddr, mux); err != nil {
		log.Fatalf("collector: server error: %v", err)
	}
}
