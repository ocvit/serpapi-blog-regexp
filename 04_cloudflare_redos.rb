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
# [macOS 15.4.1 | M4 Max]
#
# -- [cloudflare-redos/original]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby     7.215k i/100ms
#                  re2    38.000k i/100ms
#           rust/regex    49.166k i/100ms
# Calculating -------------------------------------
#                 ruby     72.430k (± 1.1%) i/s   (13.81 μs/i) -    367.965k in   5.080909s
#                  re2    378.366k (± 0.7%) i/s    (2.64 μs/i) -      1.900M in   5.021819s
#           rust/regex    485.080k (± 1.1%) i/s    (2.06 μs/i) -      2.458M in   5.068414s

# Comparison:
#           rust/regex:   485080.3 i/s
#                  re2:   378366.3 i/s - 1.28x  slower
#                 ruby:    72430.0 i/s - 6.70x  slower


# -- [cloudflare-redos/simplified-short]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby    21.128k i/100ms
#                  re2    37.527k i/100ms
#           rust/regex   391.888k i/100ms
# Calculating -------------------------------------
#                 ruby    208.465k (± 1.9%) i/s    (4.80 μs/i) -      1.056M in   5.069383s
#                  re2    377.749k (± 1.6%) i/s    (2.65 μs/i) -      1.914M in   5.067872s
#           rust/regex      3.873M (± 2.1%) i/s  (258.20 ns/i) -     19.594M in   5.061520s

# Comparison:
#           rust/regex:  3873017.0 i/s
#                  re2:   377749.0 i/s - 10.25x  slower
#                 ruby:   208464.5 i/s - 18.58x  slower


# -- [cloudflare-redos/simplified-long]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby   223.000 i/100ms
#                  re2   725.000 i/100ms
#           rust/regex    11.300k i/100ms
# Calculating -------------------------------------
#                 ruby      2.389k (± 1.8%) i/s  (418.67 μs/i) -     12.042k in   5.043238s
#                  re2      7.176k (± 1.7%) i/s  (139.36 μs/i) -     36.250k in   5.053056s
#           rust/regex    129.314k (± 7.5%) i/s    (7.73 μs/i) -    644.100k in   5.013767s

# Comparison:
#           rust/regex:   129313.7 i/s
#                  re2:     7175.9 i/s - 18.02x  slower
#                 ruby:     2388.5 i/s - 54.14x  slower
