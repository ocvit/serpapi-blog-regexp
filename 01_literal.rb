require "benchmark/ips"
require "re2"
require "rust_regexp"
require "pry"

require_relative "helpers"

# NOTES:
# - re2 requires capture group for `.scan` to return the actual matches,
#   without capture group it's just true/false

EXAMPLES = {
  "literal/sherlock-en" => {
    haystack: {
      path: "./data/opensubtitles/en-sampled.txt"
    },
    patterns: {
      ruby: 'Sherlock Holmes',
      re2: '(Sherlock Holmes)',
      rust: 'Sherlock Holmes'
    },
    validations: {
      count: {
        :* => 513
      }
    }
  },
  "literal/sherlock-casei-en" => {
    haystack: {
      path: "./data/opensubtitles/en-sampled.txt"
    },
    patterns: {
      ruby: '(?i)Sherlock Holmes',
      re2: '(?i:(Sherlock Holmes))',
      rust: '(?i)Sherlock Holmes'
    },
    validations: {
      count: {
        :* => 522
      }
    }
  },
  "literal/sherlock-ru" => {
    haystack: {
      path: "./data/opensubtitles/ru-sampled.txt"
    },
    patterns: {
      ruby: 'Шерлок Холмс',
      re2: '(Шерлок Холмс)',
      rust: 'Шерлок Холмс'
    },
    validations: {
      count: {
        :* => 724
      }
    }
  },
  "literal/sherlock-casei-ru" => {
    haystack: {
      path: "./data/opensubtitles/ru-sampled.txt"
    },
    patterns: {
      ruby: '(?i)Шерлок Холмс',
      re2: '(?i:(Шерлок Холмс))',
      rust: '(?i)Шерлок Холмс'
    },
    validations: {
      count: {
        :* => 746
      }
    }
  },
  "literal/sherlock-zh" => {
    haystack: {
      path: "./data/opensubtitles/zh-sampled.txt"
    },
    patterns: {
      ruby: '夏洛克·福尔摩斯',
      re2: '(夏洛克·福尔摩斯)',
      rust: '夏洛克·福尔摩斯'
    },
    validations: {
      count: {
        :* => 30
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
# -- [literal/sherlock-en]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby   251.000 i/100ms
#                  re2   233.000 i/100ms
#           rust/regex     1.587k i/100ms
# Calculating -------------------------------------
#                 ruby      2.513k (± 1.0%) i/s  (397.96 μs/i) -     12.801k in   5.094801s
#                  re2      2.335k (± 0.5%) i/s  (428.34 μs/i) -     11.883k in   5.090115s
#           rust/regex     15.867k (± 0.6%) i/s   (63.02 μs/i) -     79.350k in   5.001165s

# Comparison:
#           rust/regex:    15866.9 i/s
#                 ruby:     2512.8 i/s - 6.31x  slower
#                  re2:     2334.6 i/s - 6.80x  slower


# -- [literal/sherlock-casei-en]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby    17.000 i/100ms
#                  re2    42.000 i/100ms
#           rust/regex   590.000 i/100ms
# Calculating -------------------------------------
#                 ruby    172.876 (± 0.6%) i/s    (5.78 ms/i) -    867.000 in   5.015253s
#                  re2    425.255 (± 0.2%) i/s    (2.35 ms/i) -      2.142k in   5.037008s
#           rust/regex      5.905k (± 0.4%) i/s  (169.35 μs/i) -     30.090k in   5.095937s

# Comparison:
#           rust/regex:     5904.8 i/s
#                  re2:      425.3 i/s - 13.89x  slower
#                 ruby:      172.9 i/s - 34.16x  slower


# -- [literal/sherlock-ru]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby   131.000 i/100ms
#                  re2    19.000 i/100ms
#           rust/regex   879.000 i/100ms
# Calculating -------------------------------------
#                 ruby      1.301k (± 1.7%) i/s  (768.92 μs/i) -      6.550k in   5.037991s
#                  re2    197.472 (± 0.5%) i/s    (5.06 ms/i) -    988.000 in   5.003404s
#           rust/regex      8.857k (± 0.8%) i/s  (112.90 μs/i) -     44.829k in   5.061654s

# Comparison:
#           rust/regex:     8857.1 i/s
#                 ruby:     1300.5 i/s - 6.81x  slower
#                  re2:      197.5 i/s - 44.85x  slower


# -- [literal/sherlock-casei-ru]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby     6.000 i/100ms
#                  re2    24.000 i/100ms
#           rust/regex   295.000 i/100ms
# Calculating -------------------------------------
#                 ruby     68.117 (± 0.0%) i/s   (14.68 ms/i) -    342.000 in   5.020801s
#                  re2    247.802 (± 0.4%) i/s    (4.04 ms/i) -      1.248k in   5.036346s
#           rust/regex      2.945k (± 0.5%) i/s  (339.52 μs/i) -     14.750k in   5.008109s

# Comparison:
#           rust/regex:     2945.3 i/s
#                  re2:      247.8 i/s - 11.89x  slower
#                 ruby:       68.1 i/s - 43.24x  slower


# -- [literal/sherlock-zh]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby   638.000 i/100ms
#                  re2   114.000 i/100ms
#           rust/regex     3.246k i/100ms
# Calculating -------------------------------------
#                 ruby      6.395k (± 0.6%) i/s  (156.36 μs/i) -     32.538k in   5.087880s
#                  re2      1.146k (± 0.6%) i/s  (872.47 μs/i) -      5.814k in   5.072728s
#           rust/regex     32.422k (± 0.6%) i/s   (30.84 μs/i) -    162.300k in   5.005999s

# Comparison:
#           rust/regex:    32422.1 i/s
#                 ruby:     6395.4 i/s - 5.07x  slower
#                  re2:     1146.2 i/s - 28.29x  slower
#
# =========================================================================================
#
