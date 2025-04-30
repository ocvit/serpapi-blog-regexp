require "benchmark/ips"
require "re2"
require "rust_regexp"
require "pry"

require_relative "helpers"

# NOTES:
# - unicode example has been excluded as in re2 neither \d nor \s are Unicode-aware,
#   and \s being ASCII-only does impact the match count
# - selected line range differs from rebar

EXAMPLES = {
  "date/ascii" => {
    haystack: {
      path: "./data/rust-src-tools-3b0d4813.txt",
      line_start: 150_000,
      line_end: 200_000
    },
    pattern_path: "./data/date/regexp.txt",
    unicode: false,
    validations: {
      count_spans: {
        :* => 69288
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
# -- [date/ascii]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [x86_64-linux]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2     1.000 i/100ms
#           rust/regex     1.000 i/100ms
# Calculating -------------------------------------
#                 ruby      0.583 (± 0.0%) i/s     (1.71 s/i) -      3.000 in   5.141671s
#                  re2     13.299 (± 0.0%) i/s   (75.19 ms/i) -     67.000 in   5.038107s
#           rust/regex     18.069 (± 0.0%) i/s   (55.34 ms/i) -     91.000 in   5.036226s

# Comparison:
#           rust/regex:       18.1 i/s
#                  re2:       13.3 i/s - 1.36x  slower
#                 ruby:        0.6 i/s - 30.97x  slower
#
# =========================================================================================
#
# [macOS 14.7.2 | M1 Max]
#
# -- [date/ascii]
# ruby 3.4.3 (2025-04-14 revision d0b7e5b6a0) +PRISM [arm64-darwin23]
# Warming up --------------------------------------
#                 ruby     1.000 i/100ms
#                  re2     1.000 i/100ms
#           rust/regex     1.000 i/100ms
# Calculating -------------------------------------
#                 ruby      0.621 (± 0.0%) i/s     (1.61 s/i) -      4.000 in   6.447173s
#                  re2     11.897 (± 8.4%) i/s   (84.05 ms/i) -     60.000 in   5.059040s
#           rust/regex     18.683 (± 0.0%) i/s   (53.53 ms/i) -     94.000 in   5.032798s

# Comparison:
#           rust/regex:       18.7 i/s
#                  re2:       11.9 i/s - 1.57x  slower
#                 ruby:        0.6 i/s - 30.09x  slower
