require "benchmark/ips"
require "re2"
require "rust_regexp"
require "pry"

require_relative "helpers"

EXAMPLES = {
  "bounded-repeat/letters-en" => {
    haystack: {
      path: "./data/opensubtitles/en-sampled.txt",
      line_end: 5000
    },
    patterns: {
      ruby: '[A-Za-z]{8,13}',
      re2: '([A-Za-z]{8,13})',
      rust: '[A-Za-z]{8,13}'
    },
    validations: {
      count: {
        :* => 1833
      }
    }
  },
  "bounded-repeat/letters-ru" => {
    haystack: {
      path: "./data/opensubtitles/ru-sampled.txt",
      line_end: 5000
    },
    patterns: {
      ruby: '\p{L}{8,13}',
      re2: '(\p{L}{8,13})',
      rust: '\p{L}{8,13}'
    },
    validations: {
      count: {
        :* => 3475
      }
    }
  },
  "bounded-repeat/context" => {
    haystack: {
      path: "./data/rust-src-tools-3b0d4813.txt"
    },
    patterns: {
      ruby: '[A-Za-z]{10}\s+[\s\S]{0,100}Result[\s\S]{0,100}\s+[A-Za-z]{10}',
      re2: '([A-Za-z]{10}\s+[\s\S]{0,100}Result[\s\S]{0,100}\s+[A-Za-z]{10})',
      rust: '[A-Za-z]{10}\s+[\s\S]{0,100}Result[\s\S]{0,100}\s+[A-Za-z]{10}'
    },
    validations: {
      count: {
        :* => 53
      }
    }
  },
  "bounded-repeat/capitals" => {
    haystack: {
      path: "./data/rust-src-tools-3b0d4813.txt"
    },
    patterns: {
      ruby: '(?:[A-Z][a-z]+\s*){10,100}',
      re2: '((?:[A-Z][a-z]+\s*){10,100})',
      rust: '(?:[A-Z][a-z]+\s*){10,100}'
    },
    validations: {
      count: {
        :* => 11
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
# -- [bounded-repeat/letters-en]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby    16.000 i/100ms
#                  re2    69.000 i/100ms
#           rust/regex   205.000 i/100ms
# Calculating -------------------------------------
#                 ruby    160.076 (± 1.2%) i/s    (6.25 ms/i) -    816.000 in   5.098412s
#                  re2    694.208 (± 0.9%) i/s    (1.44 ms/i) -      3.519k in   5.069443s
#           rust/regex      2.046k (± 0.3%) i/s  (488.76 μs/i) -     10.250k in   5.009798s

# Comparison:
#           rust/regex:     2046.0 i/s
#                  re2:      694.2 i/s - 2.95x  slower
#                 ruby:      160.1 i/s - 12.78x  slower


# -- [bounded-repeat/letters-ru]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby     8.000 i/100ms
#                  re2     1.000 i/100ms
#           rust/regex    97.000 i/100ms
# Calculating -------------------------------------
#                 ruby     84.089 (± 0.0%) i/s   (11.89 ms/i) -    424.000 in   5.042387s
#                  re2     16.273 (±18.4%) i/s   (61.45 ms/i) -     80.000 in   5.038373s
#           rust/regex    970.406 (± 0.7%) i/s    (1.03 ms/i) -      4.947k in   5.098106s

# Comparison:
#           rust/regex:      970.4 i/s
#                 ruby:       84.1 i/s - 11.54x  slower
#                  re2:       16.3 i/s - 59.63x  slower


# -- [bounded-repeat/context]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2     1.000 i/100ms
#           rust/regex     1.000 i/100ms
# Calculating -------------------------------------
#                 ruby      3.306 (± 0.0%) i/s  (302.47 ms/i) -     17.000 in   5.142134s
#                  re2      8.342 (± 0.0%) i/s  (119.88 ms/i) -     42.000 in   5.035165s
#           rust/regex      8.506 (± 0.0%) i/s  (117.56 ms/i) -     43.000 in   5.055945s

# Comparison:
#           rust/regex:        8.5 i/s
#                  re2:        8.3 i/s - 1.02x  slower
#                 ruby:        3.3 i/s - 2.57x  slower


# -- [bounded-repeat/capitals]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2     9.000 i/100ms
#           rust/regex     7.000 i/100ms
# Calculating -------------------------------------
#                 ruby     14.767 (± 0.0%) i/s   (67.72 ms/i) -     74.000 in   5.011244s
#                  re2     91.607 (± 0.0%) i/s   (10.92 ms/i) -    459.000 in   5.010646s
#           rust/regex     77.138 (± 0.0%) i/s   (12.96 ms/i) -    392.000 in   5.081858s

# Comparison:
#                  re2:       91.6 i/s
#           rust/regex:       77.1 i/s - 1.19x  slower
#                 ruby:       14.8 i/s - 6.20x  slower
#
# =========================================================================================
#
# [macOS 14.7.2 | M1 Max]
#
# -- [bounded-repeat/letters-en]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby    16.000 i/100ms
#                  re2    63.000 i/100ms
#           rust/regex   244.000 i/100ms
# Calculating -------------------------------------
#                 ruby    168.495 (± 1.8%) i/s    (5.93 ms/i) -    848.000 in   5.034052s
#                  re2    645.614 (± 1.5%) i/s    (1.55 ms/i) -      3.276k in   5.075453s
#           rust/regex      2.446k (± 1.6%) i/s  (408.79 μs/i) -     12.444k in   5.088395s

# Comparison:
#           rust/regex:     2446.2 i/s
#                  re2:      645.6 i/s - 3.79x  slower
#                 ruby:      168.5 i/s - 14.52x  slower


# -- [bounded-repeat/letters-ru]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby    13.000 i/100ms
#                  re2     2.000 i/100ms
#           rust/regex   121.000 i/100ms
# Calculating -------------------------------------
#                 ruby    132.281 (± 1.5%) i/s    (7.56 ms/i) -    663.000 in   5.013382s
#                  re2     20.755 (± 4.8%) i/s   (48.18 ms/i) -    104.000 in   5.020026s
#           rust/regex      1.210k (± 2.0%) i/s  (826.32 μs/i) -      6.050k in   5.001236s

# Comparison:
#           rust/regex:     1210.2 i/s
#                 ruby:      132.3 i/s - 9.15x  slower
#                  re2:       20.8 i/s - 58.31x  slower


# -- [bounded-repeat/context]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2     1.000 i/100ms
#           rust/regex     1.000 i/100ms
# Calculating -------------------------------------
#                 ruby      3.655 (± 0.0%) i/s  (273.64 ms/i) -     19.000 in   5.199401s
#                  re2      8.436 (± 0.0%) i/s  (118.53 ms/i) -     43.000 in   5.103992s
#           rust/regex      9.914 (± 0.0%) i/s  (100.86 ms/i) -     50.000 in   5.046868s

# Comparison:
#           rust/regex:        9.9 i/s
#                  re2:        8.4 i/s - 1.18x  slower
#                 ruby:        3.7 i/s - 2.71x  slower


# -- [bounded-repeat/capitals]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2     6.000 i/100ms
#           rust/regex     7.000 i/100ms
# Calculating -------------------------------------
#                 ruby     15.233 (± 0.0%) i/s   (65.65 ms/i) -     77.000 in   5.056024s
#                  re2     62.064 (± 0.0%) i/s   (16.11 ms/i) -    312.000 in   5.027123s
#           rust/regex     80.028 (± 1.2%) i/s   (12.50 ms/i) -    406.000 in   5.073509s

# Comparison:
#           rust/regex:       80.0 i/s
#                  re2:       62.1 i/s - 1.29x  slower
#                 ruby:       15.2 i/s - 5.25x  slower
