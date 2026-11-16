module protstruct_diagnostic_trace
  use, intrinsic :: iso_fortran_env, only: int32, int64, real32, error_unit
  implicit none
  private

  public :: trace_begin
  public :: trace_int
  public :: trace_real
  public :: trace_bool
  public :: trace_string
  public :: trace_end
  public :: trace_close
  public :: trace_is_enabled

  character(len=*), parameter :: TRACE_ENV_VAR = "REFMAC_DIAGNOSTIC_TRACE"
  character(len=*), parameter :: TRACE_SCHEMA_ID = "protstruct_refmac_native_trace_v1"
  character(len=*), parameter :: TRACE_DECIMAL_ENCODING = "exact_from_captured_binary32_bits"
  character(len=16), parameter :: HEX_DIGITS = "0123456789ABCDEF"
  character(len=1), parameter :: BACKSLASH = achar(92)
  character(len=1), parameter :: DQUOTE = achar(34)

  integer(int32), parameter :: STATE_UNINITIALIZED = 0_int32
  integer(int32), parameter :: STATE_DISABLED = 1_int32
  integer(int32), parameter :: STATE_ACTIVE = 2_int32
  integer(int32), parameter :: STATE_CLOSED = 3_int32

  integer(int32), parameter :: MAX_PATH_CHARS = 4096_int32
  integer(int32), parameter :: MAX_NAME_CHARS = 256_int32
  integer(int32), parameter :: MAX_STRING_CHARS = 4096_int32
  integer(int32), parameter :: MAX_ESCAPED_CHARS = 6_int32 * MAX_STRING_CHARS
  integer(int32), parameter :: MAX_FIELDS_PER_RECORD = 256_int32
  integer(int32), parameter :: MAX_RECORD_CHARS = 65536_int32
  integer(int32), parameter :: MAX_DECIMAL_DIGITS = 160_int32
  integer(int32), parameter :: MAX_DECIMAL_CHARS = 200_int32

  integer(int32), save :: writer_state = STATE_UNINITIALIZED
  integer(int32), save :: trace_unit = -1_int32
  logical, save :: in_record = .false.
  integer(int64), save :: record_sequence = 0_int64

  integer(int32), save :: current_field_count = 0_int32
  character(len=MAX_NAME_CHARS), save :: current_field_names(MAX_FIELDS_PER_RECORD)
  integer(int32), save :: current_field_name_lens(MAX_FIELDS_PER_RECORD) = 0_int32

  character(len=MAX_RECORD_CHARS), save :: current_record_buf = ""
  integer(int32), save :: current_record_len = 0_int32

contains

  subroutine fail_loudly(message)
    character(len=*), intent(in) :: message
    integer :: ios

    write(error_unit, '(A,A)', iostat=ios) "protstruct_diagnostic_trace ERROR: ", message
    flush(error_unit, iostat=ios)
    error stop 1
  end subroutine fail_loudly

  subroutine format_i32_token(val, tok_out)
    integer(int32), intent(in) :: val
    character(len=32), intent(out) :: tok_out
    integer :: ios

    tok_out = ""
    write(tok_out, '(I0)', iostat=ios) val
    if (ios /= 0) then
      call fail_loudly("Failed to format int32 token")
    end if
    tok_out = adjustl(tok_out)
  end subroutine format_i32_token

  subroutine format_i64_token(val, tok_out)
    integer(int64), intent(in) :: val
    character(len=32), intent(out) :: tok_out
    integer :: ios

    tok_out = ""
    write(tok_out, '(I0)', iostat=ios) val
    if (ios /= 0) then
      call fail_loudly("Failed to format int64 token")
    end if
    tok_out = adjustl(tok_out)
  end subroutine format_i64_token

  subroutine verify_default_representation( &
      real_kind_val, int_kind_val, real_bits, int_bits, &
      real_radix, real_digits, real_minexp, real_maxexp, int_radix, int_digits)
    integer(int32), intent(out) :: real_kind_val
    integer(int32), intent(out) :: int_kind_val
    integer(int32), intent(out) :: real_bits
    integer(int32), intent(out) :: int_bits
    integer(int32), intent(out) :: real_radix
    integer(int32), intent(out) :: real_digits
    integer(int32), intent(out) :: real_minexp
    integer(int32), intent(out) :: real_maxexp
    integer(int32), intent(out) :: int_radix
    integer(int32), intent(out) :: int_digits

    real :: sample_default_real
    integer :: sample_default_int

    sample_default_real = 0.0
    sample_default_int = 0

    real_kind_val = int(kind(sample_default_real), int32)
    int_kind_val = int(kind(sample_default_int), int32)
    real_bits = int(storage_size(sample_default_real), int32)
    int_bits = int(storage_size(sample_default_int), int32)
    real_radix = int(radix(sample_default_real), int32)
    real_digits = int(digits(sample_default_real), int32)
    real_minexp = int(minexponent(sample_default_real), int32)
    real_maxexp = int(maxexponent(sample_default_real), int32)
    int_radix = int(radix(sample_default_int), int32)
    int_digits = int(digits(sample_default_int), int32)

    if (kind(sample_default_real) /= real32 .or. &
        kind(sample_default_int) /= int32 .or. &
        real_bits /= 32_int32 .or. &
        int_bits /= 32_int32 .or. &
        real_radix /= 2_int32 .or. &
        real_digits /= 24_int32 .or. &
        real_minexp /= -125_int32 .or. &
        real_maxexp /= 128_int32) then
      call fail_loudly("Unsupported default REAL/INTEGER representation; IEEE binary32 REAL32 and INTEGER32 are required")
    end if
  end subroutine verify_default_representation

  subroutine validate_trace_path(raw_path)
    character(len=*), intent(in) :: raw_path
    integer(int32) :: i, n, code

    n = int(len(raw_path), int32)
    if (n <= 0_int32) then
      call fail_loudly("Empty trace path passed to validate_trace_path")
    end if

    if (len_trim(raw_path) <= 0) then
      call fail_loudly("REFMAC_DIAGNOSTIC_TRACE must not be whitespace-only")
    end if

    if (raw_path(n:n) == ' ') then
      call fail_loudly("REFMAC_DIAGNOSTIC_TRACE has trailing space that Fortran OPEN would strip")
    end if

    do i = 1_int32, n
      code = int(iachar(raw_path(i:i)), int32)
      if (code < 32_int32 .or. code >= 127_int32) then
        call fail_loudly("REFMAC_DIAGNOSTIC_TRACE contains unsupported control or non-ASCII characters")
      end if
    end do
  end subroutine validate_trace_path

  subroutine ensure_initialized()
    character(len=MAX_PATH_CHARS) :: env_value
    integer :: env_len
    integer :: env_status
    integer(int32) :: real_kind_val, int_kind_val, real_bits, int_bits
    integer(int32) :: real_radix, real_digits, real_minexp, real_maxexp, int_radix, int_digits
    character(len=32) :: real_kind_tok, int_kind_tok, real_bits_tok, int_bits_tok
    character(len=32) :: real_radix_tok, real_digits_tok, real_minexp_tok, real_maxexp_tok
    character(len=32) :: int_radix_tok, int_digits_tok
    integer :: ios
    character(len=1024) :: header_line

    if (writer_state /= STATE_UNINITIALIZED) return

    env_value = ""
    env_len = 0
    env_status = 0
    call get_environment_variable(TRACE_ENV_VAR, value=env_value, length=env_len, status=env_status)

    if (env_status == 1) then
      writer_state = STATE_DISABLED
      return
    end if

    if (env_status == 0 .and. env_len == 0) then
      writer_state = STATE_DISABLED
      return
    end if

    if (env_status < 0 .or. env_status > 1 .or. env_len < 0 .or. env_len > MAX_PATH_CHARS) then
      call fail_loudly("Failed to read REFMAC_DIAGNOSTIC_TRACE environment variable without truncation")
    end if

    call verify_default_representation( &
      real_kind_val, int_kind_val, real_bits, int_bits, &
      real_radix, real_digits, real_minexp, real_maxexp, int_radix, int_digits)

    call validate_trace_path(env_value(1:env_len))

    open(newunit=trace_unit, file=env_value(1:env_len), &
         status='new', action='write', form='formatted', &
         access='sequential', position='rewind', iostat=ios)
    if (ios /= 0) then
      call fail_loudly("Failed to create new trace file at REFMAC_DIAGNOSTIC_TRACE")
    end if

    call format_i32_token(real_kind_val, real_kind_tok)
    call format_i32_token(int_kind_val, int_kind_tok)
    call format_i32_token(real_bits, real_bits_tok)
    call format_i32_token(int_bits, int_bits_tok)
    call format_i32_token(real_radix, real_radix_tok)
    call format_i32_token(real_digits, real_digits_tok)
    call format_i32_token(real_minexp, real_minexp_tok)
    call format_i32_token(real_maxexp, real_maxexp_tok)
    call format_i32_token(int_radix, int_radix_tok)
    call format_i32_token(int_digits, int_digits_tok)

    header_line = '{"record_type":"header","schema_id":"' // TRACE_SCHEMA_ID // &
      '","decimal_encoding":"' // TRACE_DECIMAL_ENCODING // &
      '","default_real_kind":' // trim(real_kind_tok) // &
      ',"default_integer_kind":' // trim(int_kind_tok) // &
      ',"default_real_storage_size":' // trim(real_bits_tok) // &
      ',"default_integer_storage_size":' // trim(int_bits_tok) // &
      ',"radix":' // trim(real_radix_tok) // &
      ',"digits":' // trim(real_digits_tok) // &
      ',"minexponent":' // trim(real_minexp_tok) // &
      ',"maxexponent":' // trim(real_maxexp_tok) // &
      ',"default_real_radix":' // trim(real_radix_tok) // &
      ',"default_real_digits":' // trim(real_digits_tok) // &
      ',"default_real_minexponent":' // trim(real_minexp_tok) // &
      ',"default_real_maxexponent":' // trim(real_maxexp_tok) // &
      ',"default_integer_radix":' // trim(int_radix_tok) // &
      ',"default_integer_digits":' // trim(int_digits_tok) // '}'

    write(trace_unit, '(A)', iostat=ios) trim(header_line)
    if (ios /= 0) then
      call fail_loudly("Failed to write trace header JSONL record")
    end if

    flush(trace_unit, iostat=ios)
    if (ios /= 0) then
      call fail_loudly("Failed to flush trace header JSONL record")
    end if

    writer_state = STATE_ACTIVE
    in_record = .false.
    record_sequence = 0_int64
    current_field_count = 0_int32
    current_record_len = 0_int32
  end subroutine ensure_initialized

  subroutine append_to_record(fragment)
    character(len=*), intent(in) :: fragment
    integer(int32) :: frag_len

    frag_len = int(len(fragment), int32)
    if (frag_len <= 0_int32) return
    if (current_record_len + frag_len > MAX_RECORD_CHARS) then
      call fail_loudly("Trace record exceeds maximum buffer length")
    end if
    current_record_buf(current_record_len + 1_int32 : current_record_len + frag_len) = fragment
    current_record_len = current_record_len + frag_len
  end subroutine append_to_record

  subroutine escape_json_string(raw_str, escaped_out, escaped_len)
    character(len=*), intent(in) :: raw_str
    character(len=MAX_ESCAPED_CHARS), intent(out) :: escaped_out
    integer(int32), intent(out) :: escaped_len

    integer(int32) :: i, raw_len, code, hi_nib, lo_nib
    character(len=1) :: ch

    raw_len = int(len(raw_str), int32)
    if (raw_len > MAX_STRING_CHARS) then
      call fail_loudly("Input string exceeds maximum supported length")
    end if

    escaped_out = ""
    escaped_len = 0_int32

    do i = 1_int32, raw_len
      ch = raw_str(i:i)
      code = int(iachar(ch), int32)

      if (code < 0_int32 .or. code >= 127_int32) then
        call fail_loudly("Unsupported non-ASCII or DEL character in trace string/identifier")
      else if (code == 34_int32) then
        call append_escaped_chars(escaped_out, escaped_len, BACKSLASH // DQUOTE)
      else if (code == 92_int32) then
        call append_escaped_chars(escaped_out, escaped_len, BACKSLASH // BACKSLASH)
      else if (code == 8_int32) then
        call append_escaped_chars(escaped_out, escaped_len, BACKSLASH // 'b')
      else if (code == 9_int32) then
        call append_escaped_chars(escaped_out, escaped_len, BACKSLASH // 't')
      else if (code == 10_int32) then
        call append_escaped_chars(escaped_out, escaped_len, BACKSLASH // 'n')
      else if (code == 12_int32) then
        call append_escaped_chars(escaped_out, escaped_len, BACKSLASH // 'f')
      else if (code == 13_int32) then
        call append_escaped_chars(escaped_out, escaped_len, BACKSLASH // 'r')
      else if (code < 32_int32) then
        hi_nib = ishft(code, -4)
        lo_nib = iand(code, 15_int32)
        call append_escaped_chars(escaped_out, escaped_len, &
          BACKSLASH // 'u00' // HEX_DIGITS(hi_nib + 1_int32 : hi_nib + 1_int32) // &
          HEX_DIGITS(lo_nib + 1_int32 : lo_nib + 1_int32))
      else
        call append_escaped_chars(escaped_out, escaped_len, ch)
      end if
    end do
  end subroutine escape_json_string

  subroutine append_escaped_chars(buf, cur_len, chars)
    character(len=MAX_ESCAPED_CHARS), intent(inout) :: buf
    integer(int32), intent(inout) :: cur_len
    character(len=*), intent(in) :: chars
    integer(int32) :: add_len

    add_len = int(len(chars), int32)
    if (cur_len + add_len > MAX_ESCAPED_CHARS) then
      call fail_loudly("Escaped JSON string exceeds buffer capacity")
    end if
    buf(cur_len + 1_int32 : cur_len + add_len) = chars
    cur_len = cur_len + add_len
  end subroutine append_escaped_chars

  logical function is_reserved_field_name(name_str) result(is_reserved)
    character(len=*), intent(in) :: name_str

    select case (name_str)
    case ("event", "sequence", "record_type", "schema_id", "record_count", "decimal_encoding")
      is_reserved = .true.
    case default
      is_reserved = .false.
    end select
  end function is_reserved_field_name

  subroutine register_field_name(name, escaped_name, escaped_len)
    character(len=*), intent(in) :: name
    character(len=MAX_ESCAPED_CHARS), intent(out) :: escaped_name
    integer(int32), intent(out) :: escaped_len

    integer(int32) :: raw_len, idx

    if (writer_state /= STATE_ACTIVE) then
      call fail_loudly("Trace field emitted when writer is not active (after trace_close)")
    end if
    if (.not. in_record) then
      call fail_loudly("Trace field emitted outside an active trace_begin/trace_end block")
    end if

    raw_len = int(len(name), int32)
    if (raw_len <= 0_int32 .or. len_trim(name) <= 0) then
      call fail_loudly("Trace field name must not be empty or blank")
    end if
    if (raw_len > MAX_NAME_CHARS) then
      call fail_loudly("Trace field name exceeds maximum supported length")
    end if

    if (is_reserved_field_name(name(1:raw_len)) .or. &
        is_reserved_field_name(trim(adjustl(name)))) then
      call fail_loudly("Trace field name is reserved: " // name(1:raw_len))
    end if

    do idx = 1_int32, current_field_count
      if (current_field_name_lens(idx) == raw_len) then
        if (current_field_names(idx)(1:raw_len) == name(1:raw_len)) then
          call fail_loudly("Duplicate trace field name in record: " // name(1:raw_len))
        end if
      end if
    end do

    if (current_field_count >= MAX_FIELDS_PER_RECORD) then
      call fail_loudly("Number of fields in trace record exceeds MAX_FIELDS_PER_RECORD")
    end if

    call escape_json_string(name(1:raw_len), escaped_name, escaped_len)

    current_field_count = current_field_count + 1_int32
    current_field_names(current_field_count) = ""
    current_field_names(current_field_count)(1:raw_len) = name(1:raw_len)
    current_field_name_lens(current_field_count) = raw_len
  end subroutine register_field_name

  subroutine format_int32_hex8(bits, hex_out)
    integer(int32), intent(in) :: bits
    character(len=8), intent(out) :: hex_out
    integer(int32) :: k, nib

    do k = 1_int32, 8_int32
      nib = ibits(bits, (8_int32 - k) * 4_int32, 4_int32)
      hex_out(k:k) = HEX_DIGITS(nib + 1_int32 : nib + 1_int32)
    end do
  end subroutine format_int32_hex8

  subroutine format_binary32_exact_decimal(bits, dec_out, dec_len)
    integer(int32), intent(in) :: bits
    character(len=MAX_DECIMAL_CHARS), intent(out) :: dec_out
    integer(int32), intent(out) :: dec_len

    integer(int32) :: sign_bit, exp_bits, frac_bits
    integer(int32) :: mantissa, bin_exp, rem_val
    integer(int32) :: digits_lsd(MAX_DECIMAL_DIGITS)
    integer(int32) :: num_digits, step, d_idx, carry, prod, pos, exp_tok_len
    character(len=32) :: exp_tok

    dec_out = ""
    dec_len = 0_int32

    sign_bit = ibits(bits, 31_int32, 1_int32)
    exp_bits = ibits(bits, 23_int32, 8_int32)
    frac_bits = ibits(bits, 0_int32, 23_int32)

    if (exp_bits == 255_int32) then
      if (frac_bits /= 0_int32) then
        dec_out = "NaN"
        dec_len = 3_int32
      else if (sign_bit /= 0_int32) then
        dec_out = "-Inf"
        dec_len = 4_int32
      else
        dec_out = "Inf"
        dec_len = 3_int32
      end if
      return
    end if

    if (exp_bits == 0_int32 .and. frac_bits == 0_int32) then
      if (sign_bit /= 0_int32) then
        dec_out = "-0.0"
        dec_len = 4_int32
      else
        dec_out = "0.0"
        dec_len = 3_int32
      end if
      return
    end if

    if (exp_bits == 0_int32) then
      mantissa = frac_bits
      bin_exp = -149_int32
    else
      mantissa = 8388608_int32 + frac_bits
      bin_exp = exp_bits - 150_int32
    end if

    digits_lsd = 0_int32
    num_digits = 0_int32
    rem_val = mantissa
    do while (rem_val > 0_int32)
      num_digits = num_digits + 1_int32
      digits_lsd(num_digits) = mod(rem_val, 10_int32)
      rem_val = rem_val / 10_int32
    end do

    if (bin_exp >= 0_int32) then
      do step = 1_int32, bin_exp
        carry = 0_int32
        do d_idx = 1_int32, num_digits
          prod = digits_lsd(d_idx) * 2_int32 + carry
          digits_lsd(d_idx) = mod(prod, 10_int32)
          carry = prod / 10_int32
        end do
        do while (carry > 0_int32)
          if (num_digits >= MAX_DECIMAL_DIGITS) then
            call fail_loudly("Exact decimal digit buffer overflow in trace_real")
          end if
          num_digits = num_digits + 1_int32
          digits_lsd(num_digits) = mod(carry, 10_int32)
          carry = carry / 10_int32
        end do
      end do
    else
      do step = 1_int32, -bin_exp
        carry = 0_int32
        do d_idx = 1_int32, num_digits
          prod = digits_lsd(d_idx) * 5_int32 + carry
          digits_lsd(d_idx) = mod(prod, 10_int32)
          carry = prod / 10_int32
        end do
        do while (carry > 0_int32)
          if (num_digits >= MAX_DECIMAL_DIGITS) then
            call fail_loudly("Exact decimal digit buffer overflow in trace_real")
          end if
          num_digits = num_digits + 1_int32
          digits_lsd(num_digits) = mod(carry, 10_int32)
          carry = carry / 10_int32
        end do
      end do
    end if

    pos = 0_int32
    if (sign_bit /= 0_int32) then
      pos = pos + 1_int32
      dec_out(pos:pos) = "-"
    end if

    do d_idx = num_digits, 1_int32, -1_int32
      if (pos >= MAX_DECIMAL_CHARS) then
        call fail_loudly("Exact decimal character buffer overflow in trace_real")
      end if
      pos = pos + 1_int32
      dec_out(pos:pos) = achar(iachar('0') + digits_lsd(d_idx))
    end do

    if (bin_exp < 0_int32) then
      call format_i32_token(bin_exp, exp_tok)
      exp_tok_len = int(len_trim(exp_tok), int32)
      if (pos + 1_int32 + exp_tok_len > MAX_DECIMAL_CHARS) then
        call fail_loudly("Exact decimal exponent buffer overflow in trace_real")
      end if
      pos = pos + 1_int32
      dec_out(pos:pos) = "E"
      dec_out(pos + 1_int32 : pos + exp_tok_len) = exp_tok(1:exp_tok_len)
      pos = pos + exp_tok_len
    end if

    dec_len = pos
  end subroutine format_binary32_exact_decimal

  logical function trace_is_enabled() result(enabled)
    call ensure_initialized()
    enabled = (writer_state == STATE_ACTIVE)
  end function trace_is_enabled

  subroutine trace_begin(event)
    character(len=*), intent(in) :: event

    integer(int32) :: raw_len, escaped_len
    character(len=MAX_ESCAPED_CHARS) :: escaped_event
    character(len=32) :: seq_tok

    call ensure_initialized()
    if (writer_state == STATE_DISABLED) return
    if (writer_state /= STATE_ACTIVE) then
      call fail_loudly("trace_begin called after trace_close")
    end if
    if (in_record) then
      call fail_loudly("Nested trace_begin is forbidden before trace_end")
    end if

    raw_len = int(len(event), int32)
    if (raw_len <= 0_int32 .or. len_trim(event) <= 0) then
      call fail_loudly("trace_begin event name must not be empty or blank")
    end if
    if (raw_len > MAX_NAME_CHARS) then
      call fail_loudly("trace_begin event name exceeds maximum supported length")
    end if

    call escape_json_string(event(1:raw_len), escaped_event, escaped_len)

    record_sequence = record_sequence + 1_int64
    call format_i64_token(record_sequence, seq_tok)

    current_field_count = 0_int32
    current_record_len = 0_int32
    in_record = .true.

    call append_to_record('{"sequence":' // trim(seq_tok) // &
                          ',"event":"' // escaped_event(1:escaped_len) // '"')
  end subroutine trace_begin

  subroutine trace_int(name, value)
    character(len=*), intent(in) :: name
    integer, intent(in) :: value

    character(len=MAX_ESCAPED_CHARS) :: escaped_name
    integer(int32) :: escaped_len
    character(len=32) :: int_buf
    integer :: ios

    call ensure_initialized()
    if (writer_state == STATE_DISABLED) return

    call register_field_name(name, escaped_name, escaped_len)

    int_buf = ""
    write(int_buf, '(I0)', iostat=ios) value
    if (ios /= 0) then
      call fail_loudly("Failed to format integer value in trace_int")
    end if

    call append_to_record(',"' // escaped_name(1:escaped_len) // '":' // trim(adjustl(int_buf)))
  end subroutine trace_int

  subroutine trace_real(name, value)
    character(len=*), intent(in) :: name
    real, intent(in) :: value

    character(len=MAX_ESCAPED_CHARS) :: escaped_name
    integer(int32) :: escaped_len
    integer(int32) :: bits, dec_len
    character(len=8) :: hex_str
    character(len=MAX_DECIMAL_CHARS) :: dec_str

    call ensure_initialized()
    if (writer_state == STATE_DISABLED) return

    call register_field_name(name, escaped_name, escaped_len)

    bits = transfer(value, 0_int32)
    call format_int32_hex8(bits, hex_str)
    call format_binary32_exact_decimal(bits, dec_str, dec_len)

    call append_to_record(',"' // escaped_name(1:escaped_len) // &
                          '":{"bits_hex":"' // hex_str // &
                          '","decimal":"' // dec_str(1:dec_len) // '"}')
  end subroutine trace_real

  subroutine trace_bool(name, value)
    character(len=*), intent(in) :: name
    logical, intent(in) :: value

    character(len=MAX_ESCAPED_CHARS) :: escaped_name
    integer(int32) :: escaped_len

    call ensure_initialized()
    if (writer_state == STATE_DISABLED) return

    call register_field_name(name, escaped_name, escaped_len)

    if (value) then
      call append_to_record(',"' // escaped_name(1:escaped_len) // '":true')
    else
      call append_to_record(',"' // escaped_name(1:escaped_len) // '":false')
    end if
  end subroutine trace_bool

  subroutine trace_string(name, value)
    character(len=*), intent(in) :: name
    character(len=*), intent(in) :: value

    character(len=MAX_ESCAPED_CHARS) :: escaped_name
    character(len=MAX_ESCAPED_CHARS) :: escaped_val
    integer(int32) :: escaped_name_len, escaped_val_len, val_len

    call ensure_initialized()
    if (writer_state == STATE_DISABLED) return

    call register_field_name(name, escaped_name, escaped_name_len)

    val_len = int(len(value), int32)
    if (val_len > 0_int32) then
      call escape_json_string(value(1:val_len), escaped_val, escaped_val_len)
      call append_to_record(',"' // escaped_name(1:escaped_name_len) // &
                            '":"' // escaped_val(1:escaped_val_len) // '"')
    else
      call append_to_record(',"' // escaped_name(1:escaped_name_len) // '":""')
    end if
  end subroutine trace_string

  subroutine trace_end()
    integer :: ios

    call ensure_initialized()
    if (writer_state == STATE_DISABLED) return
    if (writer_state /= STATE_ACTIVE) then
      call fail_loudly("trace_end called after trace_close")
    end if
    if (.not. in_record) then
      call fail_loudly("trace_end called without a matching trace_begin")
    end if

    call append_to_record("}")

    write(trace_unit, '(A)', iostat=ios) current_record_buf(1:current_record_len)
    if (ios /= 0) then
      call fail_loudly("Failed to write completed trace record")
    end if

    flush(trace_unit, iostat=ios)
    if (ios /= 0) then
      call fail_loudly("Failed to flush completed trace record")
    end if

    in_record = .false.
    current_field_count = 0_int32
    current_record_len = 0_int32
  end subroutine trace_end

  subroutine trace_close()
    character(len=32) :: count_tok
    character(len=256) :: close_line
    integer :: ios

    call ensure_initialized()
    if (writer_state == STATE_DISABLED) return
    if (writer_state == STATE_CLOSED) return

    if (writer_state /= STATE_ACTIVE) then
      call fail_loudly("trace_close encountered unexpected writer state")
    end if
    if (in_record) then
      call fail_loudly("trace_close called while a trace record is still open")
    end if

    call format_i64_token(record_sequence, count_tok)
    close_line = '{"record_type":"writer_close","schema_id":"' // TRACE_SCHEMA_ID // &
      '","event":"writer_close","record_count":' // trim(count_tok) // '}'

    write(trace_unit, '(A)', iostat=ios) trim(close_line)
    if (ios /= 0) then
      call fail_loudly("Failed to write writer_close JSONL record")
    end if

    flush(trace_unit, iostat=ios)
    if (ios /= 0) then
      call fail_loudly("Failed to flush writer_close JSONL record")
    end if

    close(trace_unit, status='keep', iostat=ios)
    if (ios /= 0) then
      call fail_loudly("Failed to close trace file")
    end if

    trace_unit = -1_int32
    writer_state = STATE_CLOSED
  end subroutine trace_close

end module protstruct_diagnostic_trace
