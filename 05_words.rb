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

# [macOS | M1 Max]
#
# -- [words/all-english]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby    30.000 i/100ms
#                  re2    10.000 i/100ms
#           rust/regex    72.000 i/100ms
# Calculating -------------------------------------
#                 ruby    319.228 (± 0.9%) i/s    (3.13 ms/i) -      1.620k in   5.075208s
#                  re2    101.128 (± 1.0%) i/s    (9.89 ms/i) -    510.000 in   5.043338s
#           rust/regex    743.666 (± 1.5%) i/s    (1.34 ms/i) -      3.744k in   5.035656s

# Comparison:
#           rust/regex:      743.7 i/s
#                 ruby:      319.2 i/s - 2.33x  slower
#                  re2:      101.1 i/s - 7.35x  slower


# -- [words/long-english]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby    44.000 i/100ms
#                  re2   474.000 i/100ms
#           rust/regex   108.000 i/100ms
# Calculating -------------------------------------
#                 ruby    448.989 (± 1.1%) i/s    (2.23 ms/i) -      2.288k in   5.096466s
#                  re2      4.740k (± 0.4%) i/s  (210.97 μs/i) -     24.174k in   5.100145s
#           rust/regex      1.070k (± 3.6%) i/s  (934.37 μs/i) -      5.400k in   5.053125s

# Comparison:
#                  re2:     4739.9 i/s
#           rust/regex:     1070.2 i/s - 4.43x  slower
#                 ruby:      449.0 i/s - 10.56x  slower
#
# =========================================================================================
