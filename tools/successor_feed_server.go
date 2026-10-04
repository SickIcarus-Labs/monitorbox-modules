package main

import (
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"mime"
	"net"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func main() {
	rootFlag := flag.String("root", "/feed", "immutable feed root")
	listenFlag := flag.String("listen", "127.0.0.1:18081", "loopback listener")
	flag.Parse()

	root, err := filepath.Abs(*rootFlag)
	if err != nil {
		log.Fatal(err)
	}
	info, err := os.Stat(root)
	if err != nil || !info.IsDir() {
		log.Fatalf("feed root unavailable: %v", err)
	}

	host, _, err := net.SplitHostPort(*listenFlag)
	if err != nil {
		log.Fatalf("invalid listener: %v", err)
	}
	ip := net.ParseIP(strings.Trim(host, "[]"))
	if host != "localhost" && (ip == nil || !ip.IsLoopback()) {
		log.Fatal("acceptance feed refuses non-loopback listener")
	}

	handler := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/healthz" {
			if r.Method != http.MethodGet && r.Method != http.MethodHead {
				w.Header().Set("Allow", "GET, HEAD")
				http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
				return
			}
			w.Header().Set("Cache-Control", "no-store")
			w.WriteHeader(http.StatusOK)
			if r.Method == http.MethodGet {
				_, _ = io.WriteString(w, "ok\n")
			}
			return
		}
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			w.Header().Set("Allow", "GET, HEAD")
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		if r.URL.RawQuery != "" || r.URL.Fragment != "" ||
			(!strings.HasPrefix(r.URL.Path, "/platform/channels/") &&
				!strings.HasPrefix(r.URL.Path, "/platform/packages/")) {
			http.NotFound(w, r)
			return
		}

		relative := strings.TrimPrefix(r.URL.Path, "/")
		clean := filepath.Clean(filepath.FromSlash(relative))
		if clean != filepath.FromSlash(relative) || strings.HasPrefix(clean, "..") {
			http.NotFound(w, r)
			return
		}
		filename := filepath.Join(root, clean)
		resolved, err := filepath.EvalSymlinks(filename)
		if err != nil {
			if errors.Is(err, os.ErrNotExist) {
				http.NotFound(w, r)
				return
			}
			http.Error(w, "feed unavailable", http.StatusInternalServerError)
			return
		}
		prefix := root + string(os.PathSeparator)
		if resolved != root && !strings.HasPrefix(resolved, prefix) {
			http.NotFound(w, r)
			return
		}
		file, err := os.Open(resolved)
		if err != nil {
			http.NotFound(w, r)
			return
		}
		defer file.Close()
		info, err := file.Stat()
		if err != nil || !info.Mode().IsRegular() {
			http.NotFound(w, r)
			return
		}

		switch filepath.Ext(resolved) {
		case ".json":
			w.Header().Set("Content-Type", "application/json")
		case ".zip":
			w.Header().Set("Content-Type", "application/zip")
		default:
			if value := mime.TypeByExtension(filepath.Ext(resolved)); value != "" {
				w.Header().Set("Content-Type", value)
			} else {
				w.Header().Set("Content-Type", "application/octet-stream")
			}
		}
		w.Header().Set("Cache-Control", "public, max-age=31536000, immutable")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Content-Length", fmt.Sprintf("%d", info.Size()))
		if r.Method == http.MethodHead {
			return
		}
		if _, err := io.Copy(w, file); err != nil {
			return
		}
	})

	server := &http.Server{
		Addr:              *listenFlag,
		Handler:           handler,
		ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout:       30 * time.Second,
		MaxHeaderBytes:    8 * 1024,
	}
	log.Printf("immutable successor acceptance feed listening on %s", *listenFlag)
	if err := server.ListenAndServe(); !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}
