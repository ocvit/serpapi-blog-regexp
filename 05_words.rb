require "benchmark/ips"
require "re2"
require "rust_regexp"
require "pry"

require_relative "helpers"

# NOTES:
# - re2's \b is not unicode aware, cyrillic examples can't be run with it, english one
#   has slightly different count as well (German words are not matched correctly)

EXAMPLES = {
  "words/all-english" => {
    haystack: {
      path: "./data/opensubtitles/en-sampled.txt",
      line_end: 2500
    },
    patterns: {
      ruby: '\b[0-9A-Za-z_]+\b',
      re2: '(\b[0-9A-Za-z_]+\b)',
      rust: '\b[0-9A-Za-z_]+\b'
    },
    validations: {
      count_spans: {
        :re2 => 56691,
        :* => 56601
      }
    }
  },
  "words/long-english" => {
    haystack: {
      path: "./data/opensubtitles/en-sampled.txt",
      line_end: 2500
    },
    patterns: {
      ruby: '\b[0-9A-Za-z_]{12,}\b',
      re2: '(\b[0-9A-Za-z_]{12,}\b)',
      rust: '\b[0-9A-Za-z_]{12,}\b'
    },
    validations: {
      count_spans: {
        :* => 839
      }
    }
  },
}

EXAMPLES.each do |title, example|
  puts "\n-- [#{title}]"

  haystack = prepare_haystack(example)
  regexps = prepare_regexps(example)

  validate_matches!(example, haystack, regexps)

  ruby_regexp, re2_regexp, rust_regexp = regexps.fetch_values(:ruby, :re2, :rust)

  Benchmark.ips do |x|
    x.report("ruby") do
      ruby_scan(haystack, ruby_regexp)
    end

    x.report("re2") do
      re2_scan(haystack, re2_regexp)
    end

    x.report("rust/regex") do
      rust_scan(haystack, rust_regexp)
    end

    x.compare!
  end
end


# [Ubuntu 24.04.1 LTS | DigitalOcean CPU-optimized Intel 4 vCPUs / 8 GiB]
#
# -- [words/all-english]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby    19.000 i/100ms
#                  re2    10.000 i/100ms
#           rust/regex    52.000 i/100ms
# Calculating -------------------------------------
#                 ruby    194.375 (± 1.0%) i/s    (5.14 ms/i) -    988.000 in   5.083383s
#                  re2    102.214 (± 0.0%) i/s    (9.78 ms/i) -    520.000 in   5.087453s
#           rust/regex    528.470 (± 0.6%) i/s    (1.89 ms/i) -      2.652k in   5.018450s

# Comparison:
#           rust/regex:      528.5 i/s
#                 ruby:      194.4 i/s - 2.72x  slower
#                  re2:      102.2 i/s - 5.17x  slower


# -- [words/long-english]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby    35.000 i/100ms
#                  re2   640.000 i/100ms
#           rust/regex    85.000 i/100ms
# Calculating -------------------------------------
#                 ruby    351.391 (± 0.6%) i/s    (2.85 ms/i) -      1.785k in   5.079936s
#                  re2      6.397k (± 0.5%) i/s  (156.33 μs/i) -     32.000k in   5.002787s
#           rust/regex    852.843 (± 0.2%) i/s    (1.17 ms/i) -      4.335k in   5.083041s

# Comparison:
#                  re2:     6396.6 i/s
#           rust/regex:      852.8 i/s - 7.50x  slower
#                 ruby:      351.4 i/s - 18.20x  slower
#
# =========================================================================================
#
# [macOS 15.4.1 | M4 Max]
#
# -- [words/all-english]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby    45.000 i/100ms
#                  re2    14.000 i/100ms
#           rust/regex   110.000 i/100ms
# Calculating -------------------------------------
#                 ruby    452.238 (± 1.3%) i/s    (2.21 ms/i) -      2.295k in   5.075745s
#                  re2    137.041 (± 1.5%) i/s    (7.30 ms/i) -    686.000 in   5.007512s
#           rust/regex      1.101k (± 1.2%) i/s  (908.64 μs/i) -      5.610k in   5.098159s

# Comparison:
#           rust/regex:     1100.5 i/s
#                 ruby:      452.2 i/s - 2.43x  slower
#                  re2:      137.0 i/s - 8.03x  slower


# -- [words/long-english]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby    60.000 i/100ms
#                  re2   736.000 i/100ms
#           rust/regex   157.000 i/100ms
# Calculating -------------------------------------
#                 ruby    602.433 (± 1.0%) i/s    (1.66 ms/i) -      3.060k in   5.079850s
#                  re2      7.383k (± 0.7%) i/s  (135.45 μs/i) -     37.536k in   5.084417s
#           rust/regex      1.581k (± 1.1%) i/s  (632.65 μs/i) -      8.007k in   5.066292s

# Comparison:
#                  re2:     7382.9 i/s
#           rust/regex:     1580.6 i/s - 4.67x  slower
#                 ruby:      602.4 i/s - 12.26x  slower
