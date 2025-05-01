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


# [Ubuntu 24.04.1 LTS | DigitalOcean CPU-optimized Intel 4 vCPUs / 8 GiB]
#
# -- [literal/sherlock-en]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby   217.000 i/100ms
#                  re2   251.000 i/100ms
#           rust/regex     1.227k i/100ms
# Calculating -------------------------------------
#                 ruby      2.169k (± 0.8%) i/s  (460.97 μs/i) -     10.850k in   5.001876s
#                  re2      2.510k (± 1.5%) i/s  (398.37 μs/i) -     12.550k in   5.000721s
#           rust/regex     12.248k (± 0.4%) i/s   (81.65 μs/i) -     61.350k in   5.009252s

# Comparison:
#           rust/regex:    12247.5 i/s
#                  re2:     2510.2 i/s - 4.88x  slower
#                 ruby:     2169.3 i/s - 5.65x  slower


# -- [literal/sherlock-casei-en]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby    15.000 i/100ms
#                  re2    59.000 i/100ms
#           rust/regex   561.000 i/100ms
# Calculating -------------------------------------
#                 ruby    158.153 (± 1.9%) i/s    (6.32 ms/i) -    795.000 in   5.028382s
#                  re2    596.211 (± 0.2%) i/s    (1.68 ms/i) -      3.009k in   5.046886s
#           rust/regex      5.605k (± 0.4%) i/s  (178.40 μs/i) -     28.050k in   5.004126s

# Comparison:
#           rust/regex:     5605.5 i/s
#                  re2:      596.2 i/s - 9.40x  slower
#                 ruby:      158.2 i/s - 35.44x  slower


# -- [literal/sherlock-ru]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby   115.000 i/100ms
#                  re2    28.000 i/100ms
#           rust/regex   671.000 i/100ms
# Calculating -------------------------------------
#                 ruby      1.157k (± 0.8%) i/s  (864.47 μs/i) -      5.865k in   5.070396s
#                  re2    288.332 (± 0.3%) i/s    (3.47 ms/i) -      1.456k in   5.049813s
#           rust/regex      6.721k (± 0.5%) i/s  (148.79 μs/i) -     34.221k in   5.091769s

# Comparison:
#           rust/regex:     6721.0 i/s
#                 ruby:     1156.8 i/s - 5.81x  slower
#                  re2:      288.3 i/s - 23.31x  slower


# -- [literal/sherlock-casei-ru]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby     5.000 i/100ms
#                  re2    35.000 i/100ms
#           rust/regex   271.000 i/100ms
# Calculating -------------------------------------
#                 ruby     51.814 (± 0.0%) i/s   (19.30 ms/i) -    260.000 in   5.018218s
#                  re2    352.650 (± 0.3%) i/s    (2.84 ms/i) -      1.785k in   5.061719s
#           rust/regex      2.722k (± 0.4%) i/s  (367.41 μs/i) -     13.821k in   5.077995s

# Comparison:
#           rust/regex:     2721.8 i/s
#                  re2:      352.6 i/s - 7.72x  slower
#                 ruby:       51.8 i/s - 52.53x  slower


# -- [literal/sherlock-zh]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby   634.000 i/100ms
#                  re2   223.000 i/100ms
#           rust/regex     3.024k i/100ms
# Calculating -------------------------------------
#                 ruby      6.360k (± 0.4%) i/s  (157.23 μs/i) -     32.334k in   5.083835s
#                  re2      2.233k (± 0.3%) i/s  (447.77 μs/i) -     11.373k in   5.092542s
#           rust/regex     30.128k (± 0.3%) i/s   (33.19 μs/i) -    151.200k in   5.018621s

# Comparison:
#           rust/regex:    30128.2 i/s
#                 ruby:     6360.2 i/s - 4.74x  slower
#                  re2:     2233.3 i/s - 13.49x  slower
#
# =========================================================================================
#
# [macOS 15.4.1 | M4 Max]
#
# -- [literal/sherlock-en]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby   405.000 i/100ms
#                  re2   353.000 i/100ms
#           rust/regex     2.532k i/100ms
# Calculating -------------------------------------
#                 ruby      4.082k (± 1.2%) i/s  (244.98 μs/i) -     20.655k in   5.060922s
#                  re2      3.531k (± 1.0%) i/s  (283.18 μs/i) -     18.003k in   5.098592s
#           rust/regex     25.014k (± 0.8%) i/s   (39.98 μs/i) -    126.600k in   5.061597s

# Comparison:
#           rust/regex:    25013.6 i/s
#                 ruby:     4081.9 i/s - 6.13x  slower
#                  re2:     3531.3 i/s - 7.08x  slower


# -- [literal/sherlock-casei-en]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby    25.000 i/100ms
#                  re2    67.000 i/100ms
#           rust/regex   870.000 i/100ms
# Calculating -------------------------------------
#                 ruby    257.375 (± 0.8%) i/s    (3.89 ms/i) -      1.300k in   5.051281s
#                  re2    672.302 (± 2.4%) i/s    (1.49 ms/i) -      3.417k in   5.085749s
#           rust/regex      8.419k (± 3.2%) i/s  (118.78 μs/i) -     42.630k in   5.069023s

# Comparison:
#           rust/regex:     8419.2 i/s
#                  re2:      672.3 i/s - 12.52x  slower
#                 ruby:      257.4 i/s - 32.71x  slower


# -- [literal/sherlock-ru]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby   203.000 i/100ms
#                  re2    27.000 i/100ms
#           rust/regex     1.417k i/100ms
# Calculating -------------------------------------
#                 ruby      2.020k (± 3.4%) i/s  (495.09 μs/i) -     10.150k in   5.031373s
#                  re2    280.609 (± 1.4%) i/s    (3.56 ms/i) -      1.404k in   5.004359s
#           rust/regex     14.030k (± 1.1%) i/s   (71.28 μs/i) -     70.850k in   5.050468s

# Comparison:
#           rust/regex:    14030.1 i/s
#                 ruby:     2019.8 i/s - 6.95x  slower
#                  re2:      280.6 i/s - 50.00x  slower


# -- [literal/sherlock-casei-ru]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby    10.000 i/100ms
#                  re2    39.000 i/100ms
#           rust/regex   405.000 i/100ms
# Calculating -------------------------------------
#                 ruby    101.996 (± 1.0%) i/s    (9.80 ms/i) -    510.000 in   5.000766s
#                  re2    393.050 (± 2.0%) i/s    (2.54 ms/i) -      1.989k in   5.062888s
#           rust/regex      4.168k (± 2.8%) i/s  (239.91 μs/i) -     21.060k in   5.056603s

# Comparison:
#           rust/regex:     4168.3 i/s
#                  re2:      393.0 i/s - 10.60x  slower
#                 ruby:      102.0 i/s - 40.87x  slower


# -- [literal/sherlock-zh]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin24]
# Warming up --------------------------------------
#                 ruby     1.002k i/100ms
#                  re2   189.000 i/100ms
#           rust/regex     4.851k i/100ms
# Calculating -------------------------------------
#                 ruby      9.887k (± 2.5%) i/s  (101.14 μs/i) -     50.100k in   5.070821s
#                  re2      1.940k (± 1.9%) i/s  (515.48 μs/i) -      9.828k in   5.067962s
#           rust/regex     49.706k (± 0.7%) i/s   (20.12 μs/i) -    252.252k in   5.075067s

# Comparison:
#           rust/regex:    49706.4 i/s
#                 ruby:     9886.9 i/s - 5.03x  slower
#                  re2:     1939.9 i/s - 25.62x  slower
