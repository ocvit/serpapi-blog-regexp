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


# [Ubuntu 24.04.1 LTS | DigitalOcean CPU-optimized Intel 4 vCPUs / 8 GiB]
#
# -- [cloudflare-redos/original]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby     3.868k i/100ms
#                  re2    26.501k i/100ms
#           rust/regex    30.745k i/100ms
# Calculating -------------------------------------
#                 ruby     38.874k (± 0.3%) i/s   (25.72 μs/i) -    197.268k in   5.074535s
#                  re2    269.196k (± 0.3%) i/s    (3.71 μs/i) -      1.352M in   5.020755s
#           rust/regex    307.633k (± 0.3%) i/s    (3.25 μs/i) -      1.568M in   5.097012s

# Comparison:
#           rust/regex:   307633.0 i/s
#                  re2:   269195.8 i/s - 1.14x  slower
#                 ruby:    38874.4 i/s - 7.91x  slower


# -- [cloudflare-redos/simplified-short]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby    11.924k i/100ms
#                  re2    27.567k i/100ms
#           rust/regex   229.062k i/100ms
# Calculating -------------------------------------
#                 ruby    118.655k (± 0.4%) i/s    (8.43 μs/i) -    596.200k in   5.024702s
#                  re2    275.180k (± 1.8%) i/s    (3.63 μs/i) -      1.378M in   5.010738s
#           rust/regex      2.300M (± 0.4%) i/s  (434.81 ns/i) -     11.682M in   5.079644s

# Comparison:
#           rust/regex:  2299833.5 i/s
#                  re2:   275180.0 i/s - 8.36x  slower
#                 ruby:   118655.3 i/s - 19.38x  slower


# -- [cloudflare-redos/simplified-long]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby   140.000 i/100ms
#                  re2   533.000 i/100ms
#           rust/regex     3.866k i/100ms
# Calculating -------------------------------------
#                 ruby      1.391k (± 1.0%) i/s  (719.03 μs/i) -      7.000k in   5.033739s
#                  re2      5.373k (± 0.7%) i/s  (186.13 μs/i) -     27.183k in   5.059767s
#           rust/regex     39.191k (± 1.3%) i/s   (25.52 μs/i) -    197.166k in   5.031788s

# Comparison:
#           rust/regex:    39190.6 i/s
#                  re2:     5372.7 i/s - 7.29x  slower
#                 ruby:     1390.8 i/s - 28.18x  slower
#
# =========================================================================================
#
# [macOS 14.7.2 | M1 Max]
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
