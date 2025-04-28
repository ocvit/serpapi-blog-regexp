def ruby_scan(haystack, regexp)
  haystack.scan(regexp)
end

def re2_scan(haystack, regexp)
  regexp.scan(haystack).to_a
end

def rust_scan(haystack, regexp)
  regexp.scan(haystack)
end

def re2_set_scan(haystack, set, regexps)
  matched_regex_idxs = set.match(haystack)

  matched_regex_idxs.map do |regex_idx|
    regexp = regexps[regex_idx]
    re2_scan(haystack, regexp)
  end
end

def rust_set_scan(haystack, set, regexps)
  matched_regex_idxs = set.match(haystack)

  matched_regex_idxs.map do |regex_idx|
    regexp = regexps[regex_idx]
    rust_scan(haystack, regexp)
  end
end

def prepare_haystack(example)
  path = example[:haystack].fetch(:path)
  line_start = example.dig(:haystack, :line_start)
  line_end = example.dig(:haystack, :line_end)

  haystack = File.read(path)

  if line_start || line_end
    haystack = haystack.split("\n")[line_start...line_end].join("\n")
  end

  haystack
end

def prepare_regexps(example)
  if pattern_path = example[:pattern_path]
    pattern = File.read(pattern_path)

    patterns = {
      ruby: pattern,
      re2: pattern,
      rust: pattern
    }

    compile_regexps(patterns, example)
  elsif patterns_path = example[:patterns_path]
    patterns = File.read(patterns_path).split("\n")

    re2_options = {}
    re2_options[:utf8] = false if example[:unicode] == false

    rust_options = {}
    rust_options[:unicode] = false if example[:unicode] == false

    ruby_regexps = patterns.map { Regexp.new(_1) }
    re2_regexps = patterns.map { RE2(capturize_re2_pattern(_1), **re2_options) }
    rust_regexps = patterns.map { RustRegexp.new(_1, **rust_options) }

    {
      ruby: ruby_regexps,
      re2: re2_regexps,
      rust: rust_regexps
    }
  else
    compile_regexps(example[:patterns], example)
  end
end

def prepare_sets(example)
  if patterns_path = example[:patterns_path]
    patterns = File.read(patterns_path).split("\n")

    re2_set = RE2::Set.new
    patterns.each do |pattern|
      re2_set.add(capturize_re2_pattern(pattern))
    end
    re2_set.compile

    rust_options = {}
    rust_options[:unicode] = false if example[:unicode] == false

    rust_set = RustRegexp::Set.new(patterns, **rust_options)

    {
      re2_set: re2_set,
      rust_set: rust_set
    }
  else
    raise NotImplementedError
  end
end

# NOTE:
# - re2 requires capture group for `.scan` to return the actual matches,
#   without capture group it's just true/false
def capturize_re2_pattern(pattern)
  pattern.start_with?('(') ? pattern : "(#{pattern})"
end

def compile_regexps(patterns, example)
  patterns.map do |engine, pattern|
    regexp =
      case engine
      when :ruby
        Regexp.new(pattern)
      when :re2
        options = {}
        options[:utf8] = false if example[:unicode] == false

        RE2(pattern, **options)
      when :rust
        options = {}
        options[:unicode] = false if example[:unicode] == false

        RustRegexp.new(pattern, **options)
      end

    [engine, regexp]
  end.to_h
end

def validate_matches!(example, haystack, regexps, sets = nil, haystack_valid_utf8 = nil)
  results = {}

  regexps&.each do |engine, group|
    chosen_haystack =
      if engine == :ruby
        haystack_valid_utf8 || haystack
      else
        haystack
      end

    matches =
      if group.is_a?(Array)
        group
          .map { |regexp| send("#{engine}_scan", chosen_haystack, regexp) }
          .reject(&:empty?)
      else
        matches = send("#{engine}_scan", chosen_haystack, group)
      end

    validate!(matches, example, engine)
    results[engine] = matches.flatten(1)
  end

  sets&.each do |engine, group|
    original_engine = engine.to_s.gsub(/_set$/, '').to_sym

    matches =
      if group.is_a?(Array)
        group
          .map { |set| send("#{engine}_scan", haystack, set, regexps[original_engine]) }
          .reject(&:empty?)
      else
        matches = send("#{engine}_scan", haystack, group, regexps[original_engine])
      end

    validate!(matches, example, engine)
    results[engine] = matches.flatten(1)
  end

  # engines with specific match counts should not be compared
  engines_to_skip = example[:validations].values.flat_map(&:keys).uniq - [:*]

  if results.except(*engines_to_skip).values.uniq.size != 1
    raise "Results are different between engines"
  end
end

def validate!(matches, example, engine)
  example[:validations].each do |validation, engines|
    expected_count = engines[engine] || engines[:*]

    case validation
    when :count
      match_count = matches.size

      if match_count != expected_count
        raise "Match count for `#{engine}` does not eq #{expected_count}, returned: #{match_count}"
      end
    when :count_spans
      spans_size = matches.flatten.compact.map(&:size).sum

      if spans_size != expected_count
        raise "Spans size for `#{engine}` does not eq #{expected_count}, returned: #{spans_size}"
      end
    else
      raise ArgumentError, "unknown validation: #{validation}"
    end
  end
end
