require "benchmark/ips"
require "re2"
require "rust_regexp"
require "pry"

require_relative "helpers"

# NOTES:
# - match count in the first example differs from rebar across all engines

EXAMPLES = {
  "cloudflare-redos/original" => {
    haystack: {
      path: "./data/cloudflare_redos/original.txt"
    },
    patterns: {
      ruby: '(?:(?:"|\'|\]|\}|\\|\d|(?:nan|infinity|true|false|null|undefined|symbol|math)|`|-|\+)+[)]*;?((?:\s|-|~|!|\{\}|\|\||\+)*.*(?:.*=.*)))',
      re2: '(?:(?:"|\'|\]|\}|\\|\d|(?:nan|infinity|true|false|null|undefined|symbol|math)|`|-|\+)+[)]*;?((?:\s|-|~|!|\{\}|\|\||\+)*.*(?:.*=.*)))',
      rust: '(?:(?:"|\'|\]|\}|\\|\d|(?:nan|infinity|true|false|null|undefined|symbol|math)|`|-|\+)+[)]*;?((?:\s|-|~|!|\{\}|\|\||\+)*.*(?:.*=.*)))'
    },
    validations: {
      count_spans: {
        :* => 103
      }
    }
  },
  "cloudflare-redos/simplified-short" => {
    haystack: {
      path: "./data/cloudflare_redos/simplified-short.txt"
    },
    patterns: {
      ruby: '.*.*=.*',
      re2: '(.*.*=.*)',
      rust: '.*.*=.*'
    },
    validations: {
      count_spans: {
        :* => 102
      }
    }
  },
  "cloudflare-redos/simplified-long" => {
    haystack: {
      path: "./data/cloudflare_redos/simplified-long.txt"
    },
    patterns: {
      ruby: '.*.*=.*',
      re2: '(.*.*=.*)',
      rust: '.*.*=.*'
    },
    validations: {
      count_spans: {
        :* => 10000
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
# -- [cloudflare-redos/original]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby     5.185k i/100ms
#                  re2    26.771k i/100ms
#           rust/regex    32.816k i/100ms
# Calculating -------------------------------------
#                 ruby     51.707k (± 0.4%) i/s   (19.34 μs/i) -    259.250k in   5.013927s
#                  re2    267.737k (± 0.4%) i/s    (3.74 μs/i) -      1.365M in   5.099563s
#           rust/regex    327.787k (± 0.3%) i/s    (3.05 μs/i) -      1.641M in   5.005732s

# Comparison:
#           rust/regex:   327787.5 i/s
#                  re2:   267737.2 i/s - 1.22x  slower
#                 ruby:    51706.7 i/s - 6.34x  slower


# -- [cloudflare-redos/simplified-short]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby    15.188k i/100ms
#                  re2    27.804k i/100ms
#           rust/regex   283.837k i/100ms
# Calculating -------------------------------------
#                 ruby    151.822k (± 0.7%) i/s    (6.59 μs/i) -    759.400k in   5.002154s
#                  re2    278.810k (± 0.5%) i/s    (3.59 μs/i) -      1.418M in   5.086038s
#           rust/regex      2.848M (± 0.3%) i/s  (351.14 ns/i) -     14.476M in   5.082965s

# Comparison:
#           rust/regex:  2847903.9 i/s
#                  re2:   278809.6 i/s - 10.21x  slower
#                 ruby:   151822.3 i/s - 18.76x  slower


# -- [cloudflare-redos/simplified-long]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby   171.000 i/100ms
#                  re2   504.000 i/100ms
#           rust/regex     4.594k i/100ms
# Calculating -------------------------------------
#                 ruby      1.728k (± 1.2%) i/s  (578.69 μs/i) -      8.721k in   5.047509s
#                  re2      5.067k (± 0.3%) i/s  (197.35 μs/i) -     25.704k in   5.072846s
#           rust/regex     46.325k (± 0.6%) i/s   (21.59 μs/i) -    234.294k in   5.057807s

# Comparison:
#           rust/regex:    46325.0 i/s
#                  re2:     5067.0 i/s - 9.14x  slower
#                 ruby:     1728.0 i/s - 26.81x  slower
#
# =========================================================================================
#
