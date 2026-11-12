module protstruct_diagnostic_hooks
  use, intrinsic :: iso_fortran_env, only: int32, int64
  use protstruct_diagnostic_trace, only: &
    trace_begin, trace_int, trace_real, trace_bool, trace_string, &
    trace_end, trace_close, trace_is_enabled
  implicit none
  private

  public :: trace_hook_lsq_l0
  public :: trace_hook_lsq_l0_begin
  public :: trace_hook_lsq_l0_freer
  public :: trace_hook_lsq_l0_aniso
  public :: trace_hook_lsq_l0_bulk
  public :: trace_hook_lsq_l0_parts
  public :: trace_hook_lsq_l0_end
  public :: trace_hook_lsq_l1
  public :: trace_hook_lsq_l2_with_freer
  public :: trace_hook_lsq_l2_no_freer
  public :: trace_hook_lsq_l3
  public :: trace_hook_lsq_l4_valid
  public :: trace_hook_lsq_l4_invalid
  public :: trace_hook_lsq_l5_valid
  public :: trace_hook_lsq_l5_invalid
  public :: trace_hook_lsq_l6a_valid
  public :: trace_hook_lsq_l6a_invalid
  public :: trace_hook_lsq_l6b_valid
  public :: trace_hook_lsq_l6b_invalid
  public :: trace_hook_lsq_l7
  public :: trace_hook_lsq_l8_valid
  public :: trace_hook_lsq_l8_invalid
  public :: trace_hook_lsq_l9_work_valid
  public :: trace_hook_lsq_l9_work_invalid
  public :: trace_hook_lsq_l9_free_valid
  public :: trace_hook_lsq_l9_free_invalid
  public :: trace_hook_lsq_final_carrier_work_valid
  public :: trace_hook_lsq_final_carrier_work_invalid
  public :: trace_hook_lsq_final_carrier_free_valid
  public :: trace_hook_lsq_final_carrier_free_invalid
  public :: trace_hook_lsq_l_end
  public :: trace_lsq_accumulators_valid
  public :: trace_lsq_can_capture_addition
  public :: trace_hook_sumsfs_ls_deriv
  public :: trace_hook_comp_c0
  public :: trace_hook_comp_c1
  public :: trace_hook_comp_c2
  public :: trace_hook_comp_c3
  public :: trace_hook_comp_c4
  public :: trace_hook_comp_c5
  public :: trace_hook_comp_c5_with_free
  public :: trace_hook_comp_c5_no_free
  public :: trace_hook_comp_c_end
  public :: trace_hook_normal_termination
  public :: trace_hooks_reset_for_testing

  character(len=*), parameter :: NS_RESIDUAL_LSQ = "residual_lsq"
  character(len=*), parameter :: NS_COMPLETENESS = "reporting_completeness"
  character(len=*), parameter :: NS_LIFECYCLE = "lifecycle"

  ! Private LSQ_COEF invocation state
  integer(int64), save :: lsq_call_seq = 0_int64
  integer(int64), save :: lsq_call_id = 0_int64
  logical, save :: lsq_active = .false.
  logical, save :: lsq_in_row_loop = .false.
  integer(int32), save :: lsq_expected_rows = 0_int32
  integer(int32), save :: lsq_emitted_rows = 0_int32
  integer(int32), save :: lsq_defect_count = 0_int32
  logical, save :: lsq_numeric_invalid_latched = .false.
  integer(int32), save :: lsq_numeric_invalid_first_row = 0_int32
  character(len=64), save :: lsq_numeric_invalid_hook = ""

  ! Private L0 header and deferred per-slot boundary state
  logical, save :: lsq_l0_header_open = .false.
  integer(int32), save :: lsq_l0_nbin = 0_int32
  integer(int32), save :: lsq_l0_nb1 = 0_int32
  real, allocatable, save :: lsq_l0_sminb(:)
  real, allocatable, save :: lsq_l0_smaxb(:)

  ! Private LSQ_COEF per-row state
  integer(int32), save :: lsq_cur_row = 0_int32
  logical, save :: lsq_row_input_seen = .false.
  logical, save :: lsq_row_l3_ran = .false.
  logical, save :: lsq_row_bin_matched = .false.
  integer(int32), save :: lsq_row_matched_j = 0_int32
  real, save :: lsq_row_matched_sminb = 0.0
  real, save :: lsq_row_matched_smaxb = 0.0
  logical, save :: lsq_row_shell_added = .false.
  logical, save :: lsq_row_overall_added = .false.
  logical, save :: lsq_row_invalid_addition = .false.
  integer(int32), save :: lsq_row_ifree = 0_int32
  real, save :: lsq_row_yos = 0.0
  real, save :: lsq_row_yc_all = 0.0
  real, save :: lsq_row_sigos = 0.0
  real, save :: lsq_row_dy = 0.0
  real, save :: lsq_row_wdy = 0.0
  real, save :: lsq_row_sqrtw = 0.0

  ! Track which bins executed fresh division in current LSQ_COEF call
  logical, allocatable, save :: lsq_work_div_fresh(:)
  logical, allocatable, save :: lsq_free_div_fresh(:)

  ! Private calc_completeness invocation state
  integer(int64), save :: comp_call_seq = 0_int64
  integer(int64), save :: comp_call_id = 0_int64
  logical, save :: comp_active = .false.
  integer(int32), save :: comp_expected_rows = 0_int32
  integer(int32), save :: comp_emitted_rows = 0_int32
  integer(int32), save :: comp_defect_count = 0_int32
  integer(int32), save :: comp_cur_row = 0_int32
  integer(int32), save :: comp_row_match_count = 0_int32
  integer(int32), save :: comp_row_first_bin = 0_int32
  integer(int32), save :: comp_row_last_bin = 0_int32
  logical, save :: comp_row_overall_inc = .false.
  logical, save :: comp_row_obs_inc = .false.
  logical, save :: comp_row_miss_inc = .false.

contains

  subroutine trace_hooks_reset_for_testing()
    lsq_call_seq = 0_int64
    lsq_call_id = 0_int64
    lsq_active = .false.
    lsq_in_row_loop = .false.
    lsq_expected_rows = 0_int32
    lsq_emitted_rows = 0_int32
    lsq_defect_count = 0_int32
    lsq_numeric_invalid_latched = .false.
    lsq_numeric_invalid_first_row = 0_int32
    lsq_numeric_invalid_hook = ""
    lsq_l0_header_open = .false.
    lsq_l0_nbin = 0_int32
    lsq_l0_nb1 = 0_int32
    if (allocated(lsq_l0_sminb)) deallocate(lsq_l0_sminb)
    if (allocated(lsq_l0_smaxb)) deallocate(lsq_l0_smaxb)
    lsq_cur_row = 0_int32
    lsq_row_input_seen = .false.
    lsq_row_l3_ran = .false.
    lsq_row_bin_matched = .false.
    lsq_row_matched_j = 0_int32
    lsq_row_matched_sminb = 0.0
    lsq_row_matched_smaxb = 0.0
    lsq_row_shell_added = .false.
    lsq_row_overall_added = .false.
    lsq_row_invalid_addition = .false.
    lsq_row_ifree = 0_int32
    lsq_row_yos = 0.0
    lsq_row_yc_all = 0.0
    lsq_row_sigos = 0.0
    lsq_row_dy = 0.0
    lsq_row_wdy = 0.0
    lsq_row_sqrtw = 0.0
    if (allocated(lsq_work_div_fresh)) deallocate(lsq_work_div_fresh)
    if (allocated(lsq_free_div_fresh)) deallocate(lsq_free_div_fresh)
    comp_call_seq = 0_int64
    comp_call_id = 0_int64
    comp_active = .false.
    comp_expected_rows = 0_int32
    comp_emitted_rows = 0_int32
    comp_defect_count = 0_int32
    comp_cur_row = 0_int32
    comp_row_match_count = 0_int32
    comp_row_first_bin = 0_int32
    comp_row_last_bin = 0_int32
    comp_row_overall_inc = .false.
    comp_row_obs_inc = .false.
    comp_row_miss_inc = .false.
  end subroutine trace_hooks_reset_for_testing

  subroutine format_index_key(prefix, idx, key_out, key_len)
    character(len=*), intent(in) :: prefix
    integer(int32), intent(in) :: idx
    character(len=64), intent(out) :: key_out
    integer(int32), intent(out) :: key_len
    character(len=16) :: num_buf
    integer :: ios

    num_buf = ""
    write(num_buf, '(I0)', iostat=ios) idx
    num_buf = adjustl(num_buf)
    key_out = prefix // trim(num_buf)
    key_len = int(len_trim(key_out), int32)
  end subroutine format_index_key

  logical function trace_lsq_accumulators_valid() result(is_valid)
    is_valid = lsq_active .and. (.not. lsq_numeric_invalid_latched)
  end function trace_lsq_accumulators_valid

  logical function trace_lsq_can_capture_addition() result(can_capture)
    can_capture = lsq_active .and. lsq_in_row_loop .and. &
                  (.not. lsq_numeric_invalid_latched) .and. lsq_row_l3_ran
  end function trace_lsq_can_capture_addition

  subroutine latch_lsq_numeric_invalid(row_idx, hook_id)
    integer(int32), intent(in) :: row_idx
    character(len=*), intent(in) :: hook_id

    if (.not. lsq_numeric_invalid_latched) then
      lsq_numeric_invalid_latched = .true.
      lsq_numeric_invalid_first_row = row_idx
      lsq_numeric_invalid_hook = hook_id
    end if
    lsq_row_invalid_addition = .true.
    lsq_defect_count = lsq_defect_count + 1_int32
  end subroutine latch_lsq_numeric_invalid

  subroutine close_lsq_l0_header_if_open()
    if (lsq_l0_header_open) then
      if (trace_is_enabled()) then
        call trace_end()
      end if
      lsq_l0_header_open = .false.
    end if
  end subroutine close_lsq_l0_header_if_open

  subroutine trace_hook_lsq_l0_begin( &
      nref, nobs, npart, ndens, nbin, nb1, imode, n_refined_atoms, nref_pars, &
      nsmult, ifactor_cc, lrefin, refs, freer_flag, lexpuse, &
      datasource, phase_flag, mir_flag, sminb, smaxb, &
      scale_ls_over, b_ls_over, b_ls_over_flag, b_ls_over_refine_flag, &
      b_ls_aniso_over_flag, b_ls_aniso_over_refine_flag, &
      bulk_ls_flag, scale_ls_bulk_refine_flag, b_ls_bulk_refine_flag)
    integer, intent(in) :: nref, nobs, npart, ndens, nbin, nb1, imode
    integer, intent(in) :: n_refined_atoms, nref_pars, nsmult, ifactor_cc
    logical, intent(in) :: lrefin, freer_flag, lexpuse, phase_flag, mir_flag
    character(len=*), intent(in) :: refs, datasource
    real, intent(in) :: sminb(*), smaxb(*)
    real, intent(in) :: scale_ls_over, b_ls_over
    logical, intent(in) :: b_ls_over_flag, b_ls_over_refine_flag
    logical, intent(in) :: b_ls_aniso_over_flag, b_ls_aniso_over_refine_flag
    logical, intent(in) :: bulk_ls_flag, scale_ls_bulk_refine_flag, b_ls_bulk_refine_flag

    integer(int32) :: ibin, alloc_bins

    lsq_call_seq = lsq_call_seq + 1_int64
    lsq_call_id = lsq_call_seq
    lsq_active = .true.
    lsq_in_row_loop = .true.
    lsq_expected_rows = int(nref, int32)
    lsq_emitted_rows = 0_int32
    lsq_defect_count = 0_int32
    lsq_numeric_invalid_latched = .false.
    lsq_numeric_invalid_first_row = 0_int32
    lsq_numeric_invalid_hook = ""
    lsq_cur_row = 0_int32

    alloc_bins = max(1_int32, int(nb1, int32))
    if (allocated(lsq_work_div_fresh)) deallocate(lsq_work_div_fresh)
    if (allocated(lsq_free_div_fresh)) deallocate(lsq_free_div_fresh)
    allocate(lsq_work_div_fresh(alloc_bins))
    allocate(lsq_free_div_fresh(alloc_bins))
    lsq_work_div_fresh = .false.
    lsq_free_div_fresh = .false.

    lsq_l0_header_open = .false.
    lsq_l0_nbin = int(nbin, int32)
    lsq_l0_nb1 = int(nb1, int32)
    if (allocated(lsq_l0_sminb)) deallocate(lsq_l0_sminb)
    if (allocated(lsq_l0_smaxb)) deallocate(lsq_l0_smaxb)
    if (lsq_l0_nb1 >= 1_int32) then
      allocate(lsq_l0_sminb(lsq_l0_nb1))
      allocate(lsq_l0_smaxb(lsq_l0_nb1))
      do ibin = 1_int32, lsq_l0_nb1
        lsq_l0_sminb(ibin) = sminb(ibin)
        lsq_l0_smaxb(ibin) = smaxb(ibin)
      end do
    end if

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_coef_begin")
    lsq_l0_header_open = .true.
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L0")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("NREF", nref)
    call trace_int("NOBS", nobs)
    call trace_int("NPART", npart)
    call trace_int("NDENS", ndens)
    call trace_int("NBIN", nbin)
    call trace_int("NB1", nb1)
    call trace_int("IMODE", imode)
    call trace_int("N_REFINED_ATOMS", n_refined_atoms)
    call trace_int("NREF_PARS", nref_pars)
    call trace_int("NSMULT", nsmult)
    call trace_int("IFACTOR_CC", ifactor_cc)
    call trace_bool("LREFIN", lrefin)
    call trace_string("REFS", refs)
    call trace_bool("FREER_FLAG", freer_flag)
    call trace_bool("LEXPUSE", lexpuse)
    call trace_string("DataSource", datasource)
    call trace_bool("PHASE_FLAG", phase_flag)
    call trace_bool("MIR_FLAG", mir_flag)
    call trace_real("SCALE_LS_OVER", scale_ls_over)
    call trace_real("B_LS_OVER", b_ls_over)
    call trace_bool("B_LS_OVER_FLAG", b_ls_over_flag)
    call trace_bool("B_LS_OVER_REFINE_FLAG", b_ls_over_refine_flag)
    call trace_bool("B_LS_ANISO_OVER_FLAG", b_ls_aniso_over_flag)
    call trace_bool("B_LS_ANISO_OVER_REFINE_FLAG", b_ls_aniso_over_refine_flag)
    call trace_bool("BULK_LS_FLAG", bulk_ls_flag)
    call trace_bool("SCALE_LS_BULK_REFINE_FLAG", scale_ls_bulk_refine_flag)
    call trace_bool("B_LS_BULK_REFINE_FLAG", b_ls_bulk_refine_flag)
  end subroutine trace_hook_lsq_l0_begin

  subroutine trace_hook_lsq_l0_freer(lfreerexcludeval)
    integer, intent(in) :: lfreerexcludeval

    if (.not. trace_is_enabled()) return
    call trace_int("LFreeRexcludeVal", lfreerexcludeval)
  end subroutine trace_hook_lsq_l0_freer

  subroutine trace_hook_lsq_l0_aniso(b_ls_aniso_over, rcell)
    real, intent(in) :: b_ls_aniso_over(6), rcell(6)
    integer(int32) :: ip, k_len
    character(len=64) :: key_buf

    if (.not. trace_is_enabled()) return
    do ip = 1_int32, 6_int32
      call format_index_key("B_LS_ANISO_OVER_", ip, key_buf, k_len)
      call trace_real(key_buf(1:k_len), b_ls_aniso_over(ip))
    end do
    do ip = 1_int32, 3_int32
      call format_index_key("RCELL_", ip, key_buf, k_len)
      call trace_real(key_buf(1:k_len), rcell(ip))
    end do
  end subroutine trace_hook_lsq_l0_aniso

  subroutine trace_hook_lsq_l0_bulk(scale_ls_bulk, b_ls_bulk)
    real, intent(in) :: scale_ls_bulk, b_ls_bulk

    if (.not. trace_is_enabled()) return
    call trace_real("SCALE_LS_BULK", scale_ls_bulk)
    call trace_real("B_LS_BULK", b_ls_bulk)
  end subroutine trace_hook_lsq_l0_bulk

  subroutine trace_hook_lsq_l0_parts( &
      npart, scale_ls_part, b_ls_part, scale_ls_part_refine_flag, b_ls_part_refine_flag)
    integer, intent(in) :: npart
    real, intent(in) :: scale_ls_part(*), b_ls_part(*)
    logical, intent(in) :: scale_ls_part_refine_flag(*), b_ls_part_refine_flag(*)
    integer(int32) :: ip

    call close_lsq_l0_header_if_open()
    if (.not. trace_is_enabled()) return

    do ip = 1_int32, int(npart, int32)
      call trace_begin("lsq_coef_part_scale")
      call trace_string("namespace", NS_RESIDUAL_LSQ)
      call trace_string("source_hook_id", "L0")
      call trace_int("call_id", int(lsq_call_id, int32))
      call trace_int("NPART", npart)
      call trace_int("part_index", ip)
      call trace_real("SCALE_LS_PART", scale_ls_part(ip))
      call trace_real("B_LS_PART", b_ls_part(ip))
      call trace_bool("SCALE_LS_PART_REFINE_FLAG", scale_ls_part_refine_flag(ip))
      call trace_bool("B_LS_PART_REFINE_FLAG", b_ls_part_refine_flag(ip))
      call trace_end()
    end do
  end subroutine trace_hook_lsq_l0_parts

  subroutine trace_hook_lsq_l0_end()
    integer(int32) :: ibin

    call close_lsq_l0_header_if_open()

    if (trace_is_enabled() .and. lsq_l0_nb1 >= 1_int32 .and. &
        allocated(lsq_l0_sminb) .and. allocated(lsq_l0_smaxb)) then
      do ibin = 1_int32, lsq_l0_nb1
        call trace_begin("lsq_coef_bin_bounds")
        call trace_string("namespace", NS_RESIDUAL_LSQ)
        call trace_string("source_hook_id", "L0")
        call trace_int("call_id", int(lsq_call_id, int32))
        call trace_int("NBIN", lsq_l0_nbin)
        call trace_int("NB1", lsq_l0_nb1)
        call trace_int("slot_index", ibin)
        call trace_bool("is_overall_slot", ibin == lsq_l0_nb1)
        call trace_real("SMINB", lsq_l0_sminb(ibin))
        call trace_real("SMAXB", lsq_l0_smaxb(ibin))
        call trace_end()
      end do
    end if

    lsq_l0_nbin = 0_int32
    lsq_l0_nb1 = 0_int32
    if (allocated(lsq_l0_sminb)) deallocate(lsq_l0_sminb)
    if (allocated(lsq_l0_smaxb)) deallocate(lsq_l0_smaxb)
  end subroutine trace_hook_lsq_l0_end

  subroutine trace_hook_lsq_l0( &
      nref, nobs, npart, ndens, nbin, nb1, imode, n_refined_atoms, nref_pars, &
      nsmult, ifactor_cc, lrefin, refs, freer_flag, lfreerexcludeval, lexpuse, &
      datasource, phase_flag, mir_flag, sminb, smaxb, &
      scale_ls_over, b_ls_over, b_ls_over_flag, b_ls_over_refine_flag, &
      b_ls_aniso_over_flag, b_ls_aniso_over_refine_flag, b_ls_aniso_over, rcell, &
      bulk_ls_flag, scale_ls_bulk_refine_flag, b_ls_bulk_refine_flag, &
      scale_ls_bulk, b_ls_bulk, &
      scale_ls_part, b_ls_part, scale_ls_part_refine_flag, b_ls_part_refine_flag)
    integer, intent(in) :: nref, nobs, npart, ndens, nbin, nb1, imode
    integer, intent(in) :: n_refined_atoms, nref_pars, nsmult, ifactor_cc
    logical, intent(in) :: lrefin, freer_flag, lexpuse, phase_flag, mir_flag
    character(len=*), intent(in) :: refs, datasource
    integer, intent(in) :: lfreerexcludeval
    real, intent(in) :: sminb(*), smaxb(*)
    real, intent(in) :: scale_ls_over, b_ls_over
    logical, intent(in) :: b_ls_over_flag, b_ls_over_refine_flag
    logical, intent(in) :: b_ls_aniso_over_flag, b_ls_aniso_over_refine_flag
    real, intent(in) :: b_ls_aniso_over(6), rcell(6)
    logical, intent(in) :: bulk_ls_flag, scale_ls_bulk_refine_flag, b_ls_bulk_refine_flag
    real, intent(in) :: scale_ls_bulk, b_ls_bulk
    real, intent(in) :: scale_ls_part(*), b_ls_part(*)
    logical, intent(in) :: scale_ls_part_refine_flag(*), b_ls_part_refine_flag(*)

    call trace_hook_lsq_l0_begin( &
      nref, nobs, npart, ndens, nbin, nb1, imode, n_refined_atoms, nref_pars, &
      nsmult, ifactor_cc, lrefin, refs, freer_flag, lexpuse, &
      datasource, phase_flag, mir_flag, sminb, smaxb, &
      scale_ls_over, b_ls_over, b_ls_over_flag, b_ls_over_refine_flag, &
      b_ls_aniso_over_flag, b_ls_aniso_over_refine_flag, &
      bulk_ls_flag, scale_ls_bulk_refine_flag, b_ls_bulk_refine_flag)
    if (freer_flag) then
      call trace_hook_lsq_l0_freer(lfreerexcludeval)
    end if
    if (b_ls_aniso_over_flag) then
      call trace_hook_lsq_l0_aniso(b_ls_aniso_over, rcell)
    end if
    if (bulk_ls_flag) then
      call trace_hook_lsq_l0_bulk(scale_ls_bulk, b_ls_bulk)
    end if
    if (npart > 0) then
      call trace_hook_lsq_l0_parts( &
        npart, scale_ls_part, b_ls_part, scale_ls_part_refine_flag, b_ls_part_refine_flag)
    end if
    call trace_hook_lsq_l0_end()
  end subroutine trace_hook_lsq_l0

  subroutine trace_hook_lsq_l1(row_index)
    integer, intent(in) :: row_index

    lsq_cur_row = int(row_index, int32)
    lsq_row_input_seen = .false.
    lsq_row_l3_ran = .false.
    lsq_row_bin_matched = .false.
    lsq_row_matched_j = 0_int32
    lsq_row_matched_sminb = 0.0
    lsq_row_matched_smaxb = 0.0
    lsq_row_shell_added = .false.
    lsq_row_overall_added = .false.
    lsq_row_invalid_addition = .false.
    lsq_row_ifree = 0_int32
    lsq_row_yos = 0.0
    lsq_row_yc_all = 0.0
    lsq_row_sigos = 0.0
    lsq_row_dy = 0.0
    lsq_row_wdy = 0.0
    lsq_row_sqrtw = 0.0

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_row_reset")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L1")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_bool("numeric_capture_valid_for_call", .not. lsq_numeric_invalid_latched)
    call trace_end()
  end subroutine trace_hook_lsq_l1

  subroutine trace_hook_lsq_l2_with_freer( &
      row_index, ihh, yo, so, jmn, ifree, freer_val, rsq, rho, dy_init)
    integer, intent(in) :: row_index, jmn, ifree
    integer, intent(in) :: ihh(3)
    real, intent(in) :: yo, so, freer_val, rsq, rho, dy_init

    lsq_row_input_seen = .true.
    lsq_row_ifree = int(ifree, int32)

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_row_input")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L2")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_int("H", ihh(1))
    call trace_int("K", ihh(2))
    call trace_int("L", ihh(3))
    call trace_real("YO", yo)
    call trace_real("SO", so)
    call trace_int("JMN", jmn)
    call trace_int("IFREE", ifree)
    call trace_bool("FREER_FLAG", .true.)
    call trace_real("native_FREER_value", freer_val)
    call trace_real("RSQ", rsq)
    call trace_real("RHO", rho)
    call trace_real("DY_init", dy_init)
    call trace_end()
  end subroutine trace_hook_lsq_l2_with_freer

  subroutine trace_hook_lsq_l2_no_freer( &
      row_index, ihh, yo, so, jmn, ifree, rsq, rho, dy_init)
    integer, intent(in) :: row_index, jmn, ifree
    integer, intent(in) :: ihh(3)
    real, intent(in) :: yo, so, rsq, rho, dy_init

    lsq_row_input_seen = .true.
    lsq_row_ifree = int(ifree, int32)

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_row_input")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L2")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_int("H", ihh(1))
    call trace_int("K", ihh(2))
    call trace_int("L", ihh(3))
    call trace_real("YO", yo)
    call trace_real("SO", so)
    call trace_int("JMN", jmn)
    call trace_int("IFREE", ifree)
    call trace_bool("FREER_FLAG", .false.)
    call trace_real("RSQ", rsq)
    call trace_real("RHO", rho)
    call trace_real("DY_init", dy_init)
    call trace_end()
  end subroutine trace_hook_lsq_l2_no_freer

  subroutine trace_hook_lsq_l3( &
      row_index, yos, yc_all, phase_all, sigos, sigexper, sigapp, sqrtw, dy, wdy, f_value_c)
    integer, intent(in) :: row_index
    real, intent(in) :: yos, yc_all, phase_all, sigos, sigexper, sigapp, sqrtw, dy, wdy, f_value_c

    lsq_row_l3_ran = .true.
    lsq_row_yos = yos
    lsq_row_yc_all = yc_all
    lsq_row_sigos = sigos
    lsq_row_dy = dy
    lsq_row_wdy = wdy
    lsq_row_sqrtw = sqrtw

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_row_operands")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L3")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_real("YOS", yos)
    call trace_real("YC_ALL", yc_all)
    call trace_real("PHASE_ALL", phase_all)
    call trace_real("SIGOS", sigos)
    call trace_real("SIGEXPER", sigexper)
    call trace_real("SIGAPP", sigapp)
    call trace_real("SQRTW", sqrtw)
    call trace_real("DY", dy)
    call trace_real("WDY", wdy)
    call trace_real("F_VALUE_C", f_value_c)
    call trace_end()
  end subroutine trace_hook_lsq_l3

  subroutine trace_hook_lsq_l4_valid( &
      row_index, j_bin, ifree, sminb_j, smaxb_j, nrefa_this_before, &
      afomfc_before, afofo_before, afofc_before, afcfc_before, afc_before, &
      afo_before, asig_before, wfomfc_before, wfomfc2_before, wfo_before, wfofo_before)
    integer, intent(in) :: row_index, j_bin, ifree, nrefa_this_before
    real, intent(in) :: sminb_j, smaxb_j
    real, intent(in) :: afomfc_before, afofo_before, afofc_before, afcfc_before
    real, intent(in) :: afc_before, afo_before, asig_before, wfomfc_before
    real, intent(in) :: wfomfc2_before, wfo_before, wfofo_before

    lsq_row_bin_matched = .true.
    lsq_row_matched_j = int(j_bin, int32)
    lsq_row_matched_sminb = sminb_j
    lsq_row_matched_smaxb = smaxb_j

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_shell_match_before")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L4")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_int("J", j_bin)
    call trace_int("IFREE", ifree)
    call trace_real("SMINB_J", sminb_j)
    call trace_real("SMAXB_J", smaxb_j)
    call trace_bool("numeric_capture_valid", .true.)
    call trace_int("nrefa_this_before", nrefa_this_before)
    call trace_real("AFOMFC_before", afomfc_before)
    call trace_real("AFOFO_before", afofo_before)
    call trace_real("AFOFC_before", afofc_before)
    call trace_real("AFCFC_before", afcfc_before)
    call trace_real("AFC_before", afc_before)
    call trace_real("AFO_before", afo_before)
    call trace_real("ASIG_before", asig_before)
    call trace_real("WFOMFC_before", wfomfc_before)
    call trace_real("WFOMFC2_before", wfomfc2_before)
    call trace_real("WFO_before", wfo_before)
    call trace_real("WFOFO_before", wfofo_before)
    call trace_end()
  end subroutine trace_hook_lsq_l4_valid

  subroutine trace_hook_lsq_l4_invalid( &
      row_index, j_bin, ifree, sminb_j, smaxb_j, nrefa_this_before)
    integer, intent(in) :: row_index, j_bin, ifree, nrefa_this_before
    real, intent(in) :: sminb_j, smaxb_j

    lsq_row_bin_matched = .true.
    lsq_row_matched_j = int(j_bin, int32)
    lsq_row_matched_sminb = sminb_j
    lsq_row_matched_smaxb = smaxb_j

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_shell_match_before")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L4")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_int("J", j_bin)
    call trace_int("IFREE", ifree)
    call trace_real("SMINB_J", sminb_j)
    call trace_real("SMAXB_J", smaxb_j)
    call trace_bool("numeric_capture_valid", .false.)
    call trace_int("nrefa_this_before", nrefa_this_before)
    call trace_end()
  end subroutine trace_hook_lsq_l4_invalid

  subroutine trace_hook_lsq_l5_valid( &
      row_index, j_bin, ifree, nrefa_this_after, &
      afomfc_after, afofo_after, afofc_after, afcfc_after, afc_after, &
      afo_after, asig_after, wfomfc_after, wfomfc2_after, wfo_after, wfofo_after)
    integer, intent(in) :: row_index, j_bin, ifree, nrefa_this_after
    real, intent(in) :: afomfc_after, afofo_after, afofc_after, afcfc_after
    real, intent(in) :: afc_after, afo_after, asig_after, wfomfc_after
    real, intent(in) :: wfomfc2_after, wfo_after, wfofo_after

    lsq_row_shell_added = .true.

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_shell_accum_after")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L5")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_int("J", j_bin)
    call trace_int("IFREE", ifree)
    call trace_bool("l3_operands_ran", .true.)
    call trace_bool("numeric_capture_valid", .true.)
    call trace_int("nrefa_this_after", nrefa_this_after)
    call trace_real("YOS", lsq_row_yos)
    call trace_real("YC_ALL", lsq_row_yc_all)
    call trace_real("SIGOS", lsq_row_sigos)
    call trace_real("DY", lsq_row_dy)
    call trace_real("WDY", lsq_row_wdy)
    call trace_real("SQRTW", lsq_row_sqrtw)
    call trace_real("AFOMFC_after", afomfc_after)
    call trace_real("AFOFO_after", afofo_after)
    call trace_real("AFOFC_after", afofc_after)
    call trace_real("AFCFC_after", afcfc_after)
    call trace_real("AFC_after", afc_after)
    call trace_real("AFO_after", afo_after)
    call trace_real("ASIG_after", asig_after)
    call trace_real("WFOMFC_after", wfomfc_after)
    call trace_real("WFOMFC2_after", wfomfc2_after)
    call trace_real("WFO_after", wfo_after)
    call trace_real("WFOFO_after", wfofo_after)
    call trace_end()
  end subroutine trace_hook_lsq_l5_valid

  subroutine trace_hook_lsq_l5_invalid( &
      row_index, j_bin, ifree, nrefa_this_after)
    integer, intent(in) :: row_index, j_bin, ifree, nrefa_this_after

    lsq_row_shell_added = .true.
    if (.not. lsq_row_l3_ran) then
      call latch_lsq_numeric_invalid(int(row_index, int32), "L5")
    end if

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_shell_accum_after")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L5")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_int("J", j_bin)
    call trace_int("IFREE", ifree)
    call trace_bool("l3_operands_ran", lsq_row_l3_ran)
    call trace_bool("numeric_capture_valid", .false.)
    call trace_int("nrefa_this_after", nrefa_this_after)
    if (lsq_row_l3_ran) then
      call trace_real("YOS", lsq_row_yos)
      call trace_real("YC_ALL", lsq_row_yc_all)
      call trace_real("SIGOS", lsq_row_sigos)
      call trace_real("DY", lsq_row_dy)
      call trace_real("WDY", lsq_row_wdy)
      call trace_real("SQRTW", lsq_row_sqrtw)
    end if
    call trace_end()
  end subroutine trace_hook_lsq_l5_invalid

  subroutine trace_hook_lsq_l6a_valid( &
      row_index, nb1, ifree, nrefa_this_before, &
      afomfc_before, afofo_before, afofc_before, afcfc_before, afc_before, &
      afo_before, asig_before, wfomfc_before, wfomfc2_before, wfo_before, wfofo_before)
    integer, intent(in) :: row_index, nb1, ifree, nrefa_this_before
    real, intent(in) :: afomfc_before, afofo_before, afofc_before, afcfc_before
    real, intent(in) :: afc_before, afo_before, asig_before, wfomfc_before
    real, intent(in) :: wfomfc2_before, wfo_before, wfofo_before

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_overall_accum_before")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L6a")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_int("NB1", nb1)
    call trace_int("IFREE", ifree)
    call trace_bool("l3_operands_ran", .true.)
    call trace_bool("numeric_capture_valid", .true.)
    call trace_int("nrefa_this_before", nrefa_this_before)
    call trace_real("AFOMFC_before", afomfc_before)
    call trace_real("AFOFO_before", afofo_before)
    call trace_real("AFOFC_before", afofc_before)
    call trace_real("AFCFC_before", afcfc_before)
    call trace_real("AFC_before", afc_before)
    call trace_real("AFO_before", afo_before)
    call trace_real("ASIG_before", asig_before)
    call trace_real("WFOMFC_before", wfomfc_before)
    call trace_real("WFOMFC2_before", wfomfc2_before)
    call trace_real("WFO_before", wfo_before)
    call trace_real("WFOFO_before", wfofo_before)
    call trace_end()
  end subroutine trace_hook_lsq_l6a_valid

  subroutine trace_hook_lsq_l6a_invalid( &
      row_index, nb1, ifree, nrefa_this_before)
    integer, intent(in) :: row_index, nb1, ifree, nrefa_this_before

    if (.not. lsq_row_l3_ran) then
      call latch_lsq_numeric_invalid(int(row_index, int32), "L6a")
    end if

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_overall_accum_before")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L6a")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_int("NB1", nb1)
    call trace_int("IFREE", ifree)
    call trace_bool("l3_operands_ran", lsq_row_l3_ran)
    call trace_bool("numeric_capture_valid", .false.)
    call trace_int("nrefa_this_before", nrefa_this_before)
    call trace_end()
  end subroutine trace_hook_lsq_l6a_invalid

  subroutine trace_hook_lsq_l6b_valid( &
      row_index, nb1, ifree, nrefa_this_after, &
      afomfc_after, afofo_after, afofc_after, afcfc_after, afc_after, &
      afo_after, asig_after, wfomfc_after, wfomfc2_after, wfo_after, wfofo_after)
    integer, intent(in) :: row_index, nb1, ifree, nrefa_this_after
    real, intent(in) :: afomfc_after, afofo_after, afofc_after, afcfc_after
    real, intent(in) :: afc_after, afo_after, asig_after, wfomfc_after
    real, intent(in) :: wfomfc2_after, wfo_after, wfofo_after

    lsq_row_overall_added = .true.

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_overall_accum_after")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L6b")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_int("NB1", nb1)
    call trace_int("IFREE", ifree)
    call trace_bool("l3_operands_ran", .true.)
    call trace_bool("numeric_capture_valid", .true.)
    call trace_int("nrefa_this_after", nrefa_this_after)
    call trace_real("AFOMFC_after", afomfc_after)
    call trace_real("AFOFO_after", afofo_after)
    call trace_real("AFOFC_after", afofc_after)
    call trace_real("AFCFC_after", afcfc_after)
    call trace_real("AFC_after", afc_after)
    call trace_real("AFO_after", afo_after)
    call trace_real("ASIG_after", asig_after)
    call trace_real("WFOMFC_after", wfomfc_after)
    call trace_real("WFOMFC2_after", wfomfc2_after)
    call trace_real("WFO_after", wfo_after)
    call trace_real("WFOFO_after", wfofo_after)
    call trace_end()
  end subroutine trace_hook_lsq_l6b_valid

  subroutine trace_hook_lsq_l6b_invalid( &
      row_index, nb1, ifree, nrefa_this_after)
    integer, intent(in) :: row_index, nb1, ifree, nrefa_this_after

    lsq_row_overall_added = .true.
    if (.not. lsq_row_l3_ran) then
      call latch_lsq_numeric_invalid(int(row_index, int32), "L6b")
    end if

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_overall_accum_after")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L6b")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_int("NB1", nb1)
    call trace_int("IFREE", ifree)
    call trace_bool("l3_operands_ran", lsq_row_l3_ran)
    call trace_bool("numeric_capture_valid", .false.)
    call trace_int("nrefa_this_after", nrefa_this_after)
    call trace_end()
  end subroutine trace_hook_lsq_l6b_invalid

  subroutine trace_hook_lsq_l7(row_index)
    integer, intent(in) :: row_index
    character(len=48) :: outcome

    lsq_emitted_rows = lsq_emitted_rows + 1_int32
    if (.not. lsq_row_input_seen) then
      lsq_defect_count = lsq_defect_count + 1_int32
    end if

    if (lsq_row_invalid_addition) then
      outcome = "invalid_addition_without_operands"
    else if (lsq_row_shell_added .and. lsq_row_overall_added) then
      outcome = "included_shell_and_overall"
    else if (lsq_row_bin_matched .and. (.not. lsq_row_shell_added) .and. (.not. lsq_row_overall_added)) then
      outcome = "excluded_sigma_guard_in_shell"
    else if ((.not. lsq_row_bin_matched) .and. (.not. lsq_row_overall_added)) then
      if (lsq_row_l3_ran) then
        outcome = "excluded_no_shell_match"
      else
        outcome = "excluded_sigma_and_no_shell_match"
      end if
    else
      outcome = "unexpected_branch_combination"
      lsq_defect_count = lsq_defect_count + 1_int32
    end if

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_row_terminal")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L7")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_int("IFREE", lsq_row_ifree)
    call trace_bool("l3_operands_ran", lsq_row_l3_ran)
    call trace_bool("bin_matched", lsq_row_bin_matched)
    if (lsq_row_bin_matched) then
      call trace_int("matched_bin_index", lsq_row_matched_j)
      call trace_real("matched_SMINB", lsq_row_matched_sminb)
      call trace_real("matched_SMAXB", lsq_row_matched_smaxb)
    end if
    call trace_bool("shell_added", lsq_row_shell_added)
    call trace_bool("overall_added", lsq_row_overall_added)
    call trace_bool("row_invalid_addition", lsq_row_invalid_addition)
    call trace_bool("numeric_capture_valid_for_call", .not. lsq_numeric_invalid_latched)
    call trace_string("row_outcome", trim(outcome))
    call trace_end()
  end subroutine trace_hook_lsq_l7

  subroutine trace_hook_lsq_l8_valid( &
      nbin, nb1, nbm_dim, nrefa_this, nrefa, nrefm, &
      afomfc, afofo, afofc, afcfc, afc, afo, asig, wfomfc, wfomfc2, wfo, wfofo, &
      fxray, fxfree)
    integer, intent(in) :: nbin, nb1, nbm_dim
    integer, intent(in) :: nrefa_this(2, nbm_dim), nrefa(2, nbm_dim), nrefm(2, nbm_dim)
    real, intent(in) :: afomfc(2, nbm_dim), afofo(2, nbm_dim), afofc(2, nbm_dim)
    real, intent(in) :: afcfc(2, nbm_dim), afc(2, nbm_dim), afo(2, nbm_dim)
    real, intent(in) :: asig(2, nbm_dim), wfomfc(2, nbm_dim), wfomfc2(2, nbm_dim)
    real, intent(in) :: wfo(2, nbm_dim), wfofo(2, nbm_dim)
    real, intent(in) :: fxray, fxfree

    integer(int32) :: ibin, ifree

    lsq_in_row_loop = .false.
    lsq_cur_row = 0_int32

    if (.not. trace_is_enabled()) return

    do ibin = 1_int32, int(nb1, int32)
      do ifree = 1_int32, 2_int32
        call trace_begin("lsq_raw_accumulator_slot")
        call trace_string("namespace", NS_RESIDUAL_LSQ)
        call trace_string("source_hook_id", "L8")
        call trace_int("call_id", int(lsq_call_id, int32))
        call trace_int("NBIN", nbin)
        call trace_int("NB1", nb1)
        call trace_int("slot_index", ibin)
        call trace_bool("is_overall_slot", ibin == int(nb1, int32))
        call trace_int("IFREE", ifree)
        call trace_bool("numeric_capture_valid", .true.)
        call trace_int("nrefa_this", nrefa_this(ifree, ibin))
        call trace_int("NREFA", nrefa(ifree, ibin))
        call trace_int("NREFM", nrefm(ifree, ibin))
        call trace_real("AFOMFC_raw", afomfc(ifree, ibin))
        call trace_real("AFOFO_raw", afofo(ifree, ibin))
        call trace_real("AFOFC_raw", afofc(ifree, ibin))
        call trace_real("AFCFC_raw", afcfc(ifree, ibin))
        call trace_real("AFC_raw", afc(ifree, ibin))
        call trace_real("AFO_raw", afo(ifree, ibin))
        call trace_real("ASIG_raw", asig(ifree, ibin))
        call trace_real("WFOMFC_raw", wfomfc(ifree, ibin))
        call trace_real("WFOMFC2_raw", wfomfc2(ifree, ibin))
        call trace_real("WFO_raw", wfo(ifree, ibin))
        call trace_real("WFOFO_raw", wfofo(ifree, ibin))
        if (ibin == int(nb1, int32) .and. ifree == 1_int32) then
          call trace_real("FXRAY", fxray)
        else if (ibin == int(nb1, int32) .and. ifree == 2_int32) then
          call trace_real("FXFREE", fxfree)
        end if
        call trace_end()
      end do
    end do
  end subroutine trace_hook_lsq_l8_valid

  subroutine trace_hook_lsq_l8_invalid( &
      nbin, nb1, nbm_dim, nrefa_this, nrefa, nrefm)
    integer, intent(in) :: nbin, nb1, nbm_dim
    integer, intent(in) :: nrefa_this(2, nbm_dim), nrefa(2, nbm_dim), nrefm(2, nbm_dim)

    integer(int32) :: ibin, ifree

    lsq_in_row_loop = .false.
    lsq_cur_row = 0_int32

    if (.not. trace_is_enabled()) return

    do ibin = 1_int32, int(nb1, int32)
      do ifree = 1_int32, 2_int32
        call trace_begin("lsq_raw_accumulator_slot")
        call trace_string("namespace", NS_RESIDUAL_LSQ)
        call trace_string("source_hook_id", "L8")
        call trace_int("call_id", int(lsq_call_id, int32))
        call trace_int("NBIN", nbin)
        call trace_int("NB1", nb1)
        call trace_int("slot_index", ibin)
        call trace_bool("is_overall_slot", ibin == int(nb1, int32))
        call trace_int("IFREE", ifree)
        call trace_bool("numeric_capture_valid", .false.)
        call trace_int("nrefa_this", nrefa_this(ifree, ibin))
        call trace_int("NREFA", nrefa(ifree, ibin))
        call trace_int("NREFM", nrefm(ifree, ibin))
        call trace_end()
      end do
    end do
  end subroutine trace_hook_lsq_l8_invalid

  subroutine trace_hook_lsq_l9_work_valid( &
      slot_index, nb1, nrefa_this_work, afomfc_work, afo_work, hrfac_shell_work_i)
    integer, intent(in) :: slot_index, nb1, nrefa_this_work
    real, intent(in) :: afomfc_work, afo_work, hrfac_shell_work_i

    if (allocated(lsq_work_div_fresh)) then
      if (slot_index >= 1 .and. slot_index <= size(lsq_work_div_fresh)) then
        lsq_work_div_fresh(slot_index) = .true.
      end if
    end if

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_fresh_division_work")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L9_work")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("slot_index", slot_index)
    call trace_bool("is_overall_slot", slot_index == nb1)
    call trace_int("IFREE", 1)
    call trace_bool("fresh_division_executed", .true.)
    call trace_bool("numeric_capture_valid", .true.)
    call trace_int("nrefa_this_work", nrefa_this_work)
    call trace_real("AFOMFC_work_numerator", afomfc_work)
    call trace_real("AFO_work_denominator", afo_work)
    call trace_real("HRFAC_SHELL_WORK", hrfac_shell_work_i)
    call trace_end()
  end subroutine trace_hook_lsq_l9_work_valid

  subroutine trace_hook_lsq_l9_work_invalid( &
      slot_index, nb1, nrefa_this_work)
    integer, intent(in) :: slot_index, nb1, nrefa_this_work

    if (allocated(lsq_work_div_fresh)) then
      if (slot_index >= 1 .and. slot_index <= size(lsq_work_div_fresh)) then
        lsq_work_div_fresh(slot_index) = .true.
      end if
    end if

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_fresh_division_work")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L9_work")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("slot_index", slot_index)
    call trace_bool("is_overall_slot", slot_index == nb1)
    call trace_int("IFREE", 1)
    call trace_bool("fresh_division_executed", .true.)
    call trace_bool("numeric_capture_valid", .false.)
    call trace_int("nrefa_this_work", nrefa_this_work)
    call trace_end()
  end subroutine trace_hook_lsq_l9_work_invalid

  subroutine trace_hook_lsq_l9_free_valid( &
      slot_index, nb1, nrefa_this_free, afomfc_free, afo_free, hrfac_shell_free_i)
    integer, intent(in) :: slot_index, nb1, nrefa_this_free
    real, intent(in) :: afomfc_free, afo_free, hrfac_shell_free_i

    if (allocated(lsq_free_div_fresh)) then
      if (slot_index >= 1 .and. slot_index <= size(lsq_free_div_fresh)) then
        lsq_free_div_fresh(slot_index) = .true.
      end if
    end if

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_fresh_division_free")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L9_free")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("slot_index", slot_index)
    call trace_bool("is_overall_slot", slot_index == nb1)
    call trace_int("IFREE", 2)
    call trace_bool("fresh_division_executed", .true.)
    call trace_bool("numeric_capture_valid", .true.)
    call trace_int("nrefa_this_free", nrefa_this_free)
    call trace_real("AFOMFC_free_numerator", afomfc_free)
    call trace_real("AFO_free_denominator", afo_free)
    call trace_real("HRFAC_SHELL_FREE", hrfac_shell_free_i)
    call trace_end()
  end subroutine trace_hook_lsq_l9_free_valid

  subroutine trace_hook_lsq_l9_free_invalid( &
      slot_index, nb1, nrefa_this_free)
    integer, intent(in) :: slot_index, nb1, nrefa_this_free

    if (allocated(lsq_free_div_fresh)) then
      if (slot_index >= 1 .and. slot_index <= size(lsq_free_div_fresh)) then
        lsq_free_div_fresh(slot_index) = .true.
      end if
    end if

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_fresh_division_free")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "L9_free")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("slot_index", slot_index)
    call trace_bool("is_overall_slot", slot_index == nb1)
    call trace_int("IFREE", 2)
    call trace_bool("fresh_division_executed", .true.)
    call trace_bool("numeric_capture_valid", .false.)
    call trace_int("nrefa_this_free", nrefa_this_free)
    call trace_end()
  end subroutine trace_hook_lsq_l9_free_invalid

  subroutine trace_hook_lsq_final_carrier_work_valid( &
      nb1, nrefa_this_work_nb1, nrefa_work_nb1, hrfac_shell_work_nb1, rfactor_work_val)
    integer, intent(in) :: nb1, nrefa_this_work_nb1, nrefa_work_nb1
    real, intent(in) :: hrfac_shell_work_nb1, rfactor_work_val
    logical :: fresh_nb1

    if (nrefa_this_work_nb1 <= 0 .or. (.not. trace_lsq_accumulators_valid())) then
      call trace_hook_lsq_final_carrier_work_invalid( &
        nb1, nrefa_this_work_nb1, nrefa_work_nb1)
      return
    end if

    fresh_nb1 = .false.
    if (allocated(lsq_work_div_fresh)) then
      if (nb1 >= 1 .and. nb1 <= size(lsq_work_div_fresh)) then
        fresh_nb1 = lsq_work_div_fresh(nb1)
      end if
    end if

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_final_carrier_work")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "final_carrier_work")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("NB1", nb1)
    call trace_bool("is_carrier_assignment_only", .true.)
    call trace_bool("fresh_division_in_current_call", fresh_nb1)
    call trace_bool("numeric_capture_valid", .true.)
    call trace_int("nrefa_this_work_NB1", nrefa_this_work_nb1)
    call trace_int("NREFA_work_NB1", nrefa_work_nb1)
    call trace_real("HRFAC_SHELL_WORK_NB1", hrfac_shell_work_nb1)
    call trace_real("RFACTOR_WORK", rfactor_work_val)
    call trace_end()
  end subroutine trace_hook_lsq_final_carrier_work_valid

  subroutine trace_hook_lsq_final_carrier_work_invalid( &
      nb1, nrefa_this_work_nb1, nrefa_work_nb1)
    integer, intent(in) :: nb1, nrefa_this_work_nb1, nrefa_work_nb1
    logical :: fresh_nb1

    fresh_nb1 = .false.
    if (allocated(lsq_work_div_fresh)) then
      if (nb1 >= 1 .and. nb1 <= size(lsq_work_div_fresh)) then
        fresh_nb1 = lsq_work_div_fresh(nb1)
      end if
    end if

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_final_carrier_work")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "final_carrier_work")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("NB1", nb1)
    call trace_bool("is_carrier_assignment_only", .true.)
    call trace_bool("fresh_division_in_current_call", fresh_nb1)
    call trace_bool("numeric_capture_valid", .false.)
    call trace_int("nrefa_this_work_NB1", nrefa_this_work_nb1)
    call trace_int("NREFA_work_NB1", nrefa_work_nb1)
    call trace_end()
  end subroutine trace_hook_lsq_final_carrier_work_invalid

  subroutine trace_hook_lsq_final_carrier_free_valid( &
      nb1, nrefa_this_free_nb1, nrefa_free_nb1, nhrefl_free_val, &
      hrfac_shell_free_nb1, rfactor_free_val)
    integer, intent(in) :: nb1, nrefa_this_free_nb1, nrefa_free_nb1, nhrefl_free_val
    real, intent(in) :: hrfac_shell_free_nb1, rfactor_free_val
    logical :: fresh_nb1

    fresh_nb1 = .false.
    if (allocated(lsq_free_div_fresh)) then
      if (nb1 >= 1 .and. nb1 <= size(lsq_free_div_fresh)) then
        fresh_nb1 = lsq_free_div_fresh(nb1)
      end if
    end if

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_final_carrier_free")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "final_carrier_free")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("NB1", nb1)
    call trace_bool("is_carrier_assignment_only", .true.)
    call trace_bool("fresh_division_in_current_call", fresh_nb1)
    call trace_bool("numeric_capture_valid", .true.)
    call trace_int("nrefa_this_free_NB1", nrefa_this_free_nb1)
    call trace_int("NREFA_free_NB1", nrefa_free_nb1)
    call trace_int("NHREFL_FREE", nhrefl_free_val)
    call trace_real("HRFAC_SHELL_FREE_NB1", hrfac_shell_free_nb1)
    call trace_real("RFACTOR_FREE", rfactor_free_val)
    call trace_end()
  end subroutine trace_hook_lsq_final_carrier_free_valid

  subroutine trace_hook_lsq_final_carrier_free_invalid( &
      nb1, nrefa_this_free_nb1, nrefa_free_nb1, nhrefl_free_val)
    integer, intent(in) :: nb1, nrefa_this_free_nb1, nrefa_free_nb1, nhrefl_free_val
    logical :: fresh_nb1

    fresh_nb1 = .false.
    if (allocated(lsq_free_div_fresh)) then
      if (nb1 >= 1 .and. nb1 <= size(lsq_free_div_fresh)) then
        fresh_nb1 = lsq_free_div_fresh(nb1)
      end if
    end if

    if (.not. trace_is_enabled()) return

    call trace_begin("lsq_final_carrier_free")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "final_carrier_free")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("NB1", nb1)
    call trace_bool("is_carrier_assignment_only", .true.)
    call trace_bool("fresh_division_in_current_call", fresh_nb1)
    call trace_bool("numeric_capture_valid", .false.)
    call trace_int("nrefa_this_free_NB1", nrefa_this_free_nb1)
    call trace_int("NREFA_free_NB1", nrefa_free_nb1)
    call trace_int("NHREFL_FREE", nhrefl_free_val)
    call trace_end()
  end subroutine trace_hook_lsq_final_carrier_free_invalid

  subroutine trace_hook_lsq_l_end()
    call close_lsq_l0_header_if_open()

    if (lsq_emitted_rows /= lsq_expected_rows) then
      lsq_defect_count = lsq_defect_count + 1_int32
    end if

    if (trace_is_enabled()) then
      call trace_begin("lsq_coef_end")
      call trace_string("namespace", NS_RESIDUAL_LSQ)
      call trace_string("source_hook_id", "L_end")
      call trace_int("call_id", int(lsq_call_id, int32))
      call trace_int("expected_rows", lsq_expected_rows)
      call trace_int("emitted_rows", lsq_emitted_rows)
      call trace_bool("row_count_matches", lsq_emitted_rows == lsq_expected_rows)
      call trace_bool("numeric_capture_valid", .not. lsq_numeric_invalid_latched)
      call trace_bool("numeric_invalid_latched", lsq_numeric_invalid_latched)
      if (lsq_numeric_invalid_latched) then
        call trace_int("numeric_invalid_first_row", lsq_numeric_invalid_first_row)
        call trace_string("numeric_invalid_hook", trim(lsq_numeric_invalid_hook))
      end if
      call trace_int("defect_count", lsq_defect_count)
      call trace_end()
    end if

    lsq_active = .false.
    lsq_in_row_loop = .false.
    lsq_call_id = 0_int64
    lsq_expected_rows = 0_int32
    lsq_emitted_rows = 0_int32
    lsq_defect_count = 0_int32
    lsq_numeric_invalid_latched = .false.
    lsq_numeric_invalid_first_row = 0_int32
    lsq_numeric_invalid_hook = ""
    lsq_l0_nbin = 0_int32
    lsq_l0_nb1 = 0_int32
    if (allocated(lsq_l0_sminb)) deallocate(lsq_l0_sminb)
    if (allocated(lsq_l0_smaxb)) deallocate(lsq_l0_smaxb)
    lsq_cur_row = 0_int32
    if (allocated(lsq_work_div_fresh)) deallocate(lsq_work_div_fresh)
    if (allocated(lsq_free_div_fresh)) deallocate(lsq_free_div_fresh)
  end subroutine trace_hook_lsq_l_end

  subroutine trace_hook_sumsfs_ls_deriv( &
      ir, nref, ndens, imode, npart, nobs, ihh, &
      rsq, rho, yo, yos, sigos, expan, dbulk, expan_bulk, exp_prot, expan_bulk_scale, &
      yc0, yc_all0, phi0, phi_all, ac_all, bc_all, yc_all, delta)
    integer, intent(in) :: ir, nref, ndens, imode, npart, nobs
    integer, intent(in) :: ihh(3)
    real, intent(in) :: rsq, rho, yo, yos, sigos, expan, dbulk, expan_bulk
    real, intent(in) :: exp_prot, expan_bulk_scale, yc0, yc_all0, phi0, phi_all
    real, intent(in) :: ac_all, bc_all, yc_all, delta

    if (.not. lsq_active) return
    if (.not. lsq_in_row_loop) return
    if (int(ir, int32) /= lsq_cur_row) then
      lsq_defect_count = lsq_defect_count + 1_int32
      return
    end if
    if (.not. trace_is_enabled()) return

    call trace_begin("sumsfs_ls_deriv_row")
    call trace_string("namespace", NS_RESIDUAL_LSQ)
    call trace_string("source_hook_id", "S0_sumsfs_ls_deriv")
    call trace_int("call_id", int(lsq_call_id, int32))
    call trace_int("row_index", ir)
    call trace_int("NREF", nref)
    call trace_int("NDENS", ndens)
    call trace_int("IMODE", imode)
    call trace_int("NPART", npart)
    call trace_int("NOBS", nobs)
    call trace_int("H", ihh(1))
    call trace_int("K", ihh(2))
    call trace_int("L", ihh(3))
    call trace_real("RSQ", rsq)
    call trace_real("RHO", rho)
    call trace_real("YO", yo)
    call trace_real("YOS", yos)
    call trace_real("SIGOS", sigos)
    call trace_real("EXPAN", expan)
    call trace_real("DBULK", dbulk)
    call trace_real("EXPAN_BULK", expan_bulk)
    call trace_real("EXP_PROT", exp_prot)
    call trace_real("EXPAN_BULK_SCALE", expan_bulk_scale)
    call trace_real("YC0", yc0)
    call trace_real("YC_ALL0", yc_all0)
    call trace_real("PHI0", phi0)
    call trace_real("PHI_ALL", phi_all)
    call trace_real("AC_ALL", ac_all)
    call trace_real("BC_ALL", bc_all)
    call trace_real("YC_ALL", yc_all)
    call trace_real("DELTA", delta)
    call trace_end()
  end subroutine trace_hook_sumsfs_ls_deriv

  subroutine trace_hook_comp_c0( &
      nsym, nasym, nref, nbin, nb1, res_max, freer_flag, cell, cell_l, &
      ast, bst, cst, cosast, cosbst, coscst, sminb, smaxb)
    integer, intent(in) :: nsym, nasym, nref, nbin, nb1
    real, intent(in) :: res_max
    logical, intent(in) :: freer_flag
    real, intent(in) :: cell(6), cell_l(6)
    real, intent(in) :: ast, bst, cst, cosast, cosbst, coscst
    real, intent(in) :: sminb(*), smaxb(*)

    integer(int32) :: k, k_len, ibin
    character(len=64) :: key_buf

    comp_call_seq = comp_call_seq + 1_int64
    comp_call_id = comp_call_seq
    comp_active = .true.
    comp_expected_rows = int(nasym, int32)
    comp_emitted_rows = 0_int32
    comp_defect_count = 0_int32
    comp_cur_row = 0_int32

    if (.not. trace_is_enabled()) return

    call trace_begin("completeness_begin")
    call trace_string("namespace", NS_COMPLETENESS)
    call trace_string("source_hook_id", "C0")
    call trace_int("call_id", int(comp_call_id, int32))
    call trace_int("NSYM", nsym)
    call trace_int("NASYM", nasym)
    call trace_int("NREF", nref)
    call trace_int("NBIN", nbin)
    call trace_int("NB1", nb1)
    call trace_real("RES_MAX", res_max)
    call trace_bool("FREER_FLAG", freer_flag)
    do k = 1_int32, 6_int32
      call format_index_key("CELL_", k, key_buf, k_len)
      call trace_real(key_buf(1:k_len), cell(k))
      call format_index_key("CELL_L_", k, key_buf, k_len)
      call trace_real(key_buf(1:k_len), cell_l(k))
    end do
    call trace_real("AST", ast)
    call trace_real("BST", bst)
    call trace_real("CST", cst)
    call trace_real("COSAST", cosast)
    call trace_real("COSBST", cosbst)
    call trace_real("COSCST", coscst)
    call trace_end()

    if (nb1 >= 1) then
      do ibin = 1_int32, int(nb1, int32)
        call trace_begin("completeness_bin_bounds")
        call trace_string("namespace", NS_COMPLETENESS)
        call trace_string("source_hook_id", "C0")
        call trace_int("call_id", int(comp_call_id, int32))
        call trace_int("NBIN", nbin)
        call trace_int("NB1", nb1)
        call trace_int("slot_index", ibin)
        call trace_bool("is_overall_slot", ibin == int(nb1, int32))
        call trace_real("SMINB", sminb(ibin))
        call trace_real("SMAXB", smaxb(ibin))
        call trace_end()
      end do
    end if
  end subroutine trace_hook_comp_c0

  subroutine trace_hook_comp_c1( &
      row_index, h_asu, k_asu, l_asu, obs_code, part_code, jmn, ifree, rsq, rho)
    integer, intent(in) :: row_index, h_asu, k_asu, l_asu, obs_code, part_code, jmn, ifree
    real, intent(in) :: rsq, rho

    comp_cur_row = int(row_index, int32)
    comp_row_match_count = 0_int32
    comp_row_first_bin = 0_int32
    comp_row_last_bin = 0_int32
    comp_row_overall_inc = .false.
    comp_row_obs_inc = .false.
    comp_row_miss_inc = .false.

    if (.not. trace_is_enabled()) return

    call trace_begin("completeness_row_input")
    call trace_string("namespace", NS_COMPLETENESS)
    call trace_string("source_hook_id", "C1")
    call trace_int("call_id", int(comp_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_int("asu_H", h_asu)
    call trace_int("asu_K", k_asu)
    call trace_int("asu_L", l_asu)
    call trace_int("completeness_observed_code", obs_code)
    call trace_int("completeness_partition_code", part_code)
    call trace_int("JMN", jmn)
    call trace_int("IFREE", ifree)
    call trace_real("RSQ", rsq)
    call trace_real("RHO", rho)
    call trace_end()
  end subroutine trace_hook_comp_c1

  subroutine trace_hook_comp_c2( &
      row_index, j_bin, ifree, obs_code, sminb_j, smaxb_j, nrefa_ij, nrefm_ij)
    integer, intent(in) :: row_index, j_bin, ifree, obs_code, nrefa_ij, nrefm_ij
    real, intent(in) :: sminb_j, smaxb_j

    comp_row_match_count = comp_row_match_count + 1_int32
    if (comp_row_match_count == 1_int32) then
      comp_row_first_bin = int(j_bin, int32)
    end if
    comp_row_last_bin = int(j_bin, int32)

    if (.not. trace_is_enabled()) return

    call trace_begin("completeness_shell_increment")
    call trace_string("namespace", NS_COMPLETENESS)
    call trace_string("source_hook_id", "C2")
    call trace_int("call_id", int(comp_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_int("J", j_bin)
    call trace_int("IFREE", ifree)
    call trace_int("completeness_observed_code", obs_code)
    call trace_bool("incremented_observed", obs_code > 0)
    call trace_real("SMINB_J", sminb_j)
    call trace_real("SMAXB_J", smaxb_j)
    call trace_int("NREFA_after", nrefa_ij)
    call trace_int("NREFM_after", nrefm_ij)
    call trace_end()
  end subroutine trace_hook_comp_c2

  subroutine trace_hook_comp_c3( &
      row_index, nb1, ifree, obs_code, nrefa_nb1, nrefm_nb1)
    integer, intent(in) :: row_index, nb1, ifree, obs_code, nrefa_nb1, nrefm_nb1

    comp_row_overall_inc = .true.
    if (obs_code > 0) then
      comp_row_obs_inc = .true.
    else
      comp_row_miss_inc = .true.
    end if

    if (.not. trace_is_enabled()) return

    call trace_begin("completeness_overall_increment")
    call trace_string("namespace", NS_COMPLETENESS)
    call trace_string("source_hook_id", "C3")
    call trace_int("call_id", int(comp_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_int("NB1", nb1)
    call trace_int("IFREE", ifree)
    call trace_int("completeness_observed_code", obs_code)
    call trace_bool("incremented_observed", obs_code > 0)
    call trace_int("NREFA_NB1_after", nrefa_nb1)
    call trace_int("NREFM_NB1_after", nrefm_nb1)
    call trace_end()
  end subroutine trace_hook_comp_c3

  subroutine trace_hook_comp_c4(row_index, ifree, obs_code)
    integer, intent(in) :: row_index, ifree, obs_code
    character(len=48) :: outcome

    comp_emitted_rows = comp_emitted_rows + 1_int32
    if (int(row_index, int32) /= comp_cur_row .or. (.not. comp_row_overall_inc)) then
      comp_defect_count = comp_defect_count + 1_int32
    end if

    if (comp_row_obs_inc) then
      if (comp_row_match_count > 0_int32) then
        outcome = "observed_shell_and_overall"
      else
        outcome = "observed_overall_only_no_shell"
      end if
    else
      if (comp_row_match_count > 0_int32) then
        outcome = "missing_shell_and_overall"
      else
        outcome = "missing_overall_only_no_shell"
      end if
    end if

    if (.not. trace_is_enabled()) return

    call trace_begin("completeness_row_terminal")
    call trace_string("namespace", NS_COMPLETENESS)
    call trace_string("source_hook_id", "C4")
    call trace_int("call_id", int(comp_call_id, int32))
    call trace_int("row_index", row_index)
    call trace_int("IFREE", ifree)
    call trace_int("completeness_observed_code", obs_code)
    call trace_int("matched_shell_count", comp_row_match_count)
    if (comp_row_match_count > 0_int32) then
      call trace_int("first_matched_bin", comp_row_first_bin)
      call trace_int("last_matched_bin", comp_row_last_bin)
    end if
    call trace_bool("overall_incremented", comp_row_overall_inc)
    call trace_bool("observed_incremented", comp_row_obs_inc)
    call trace_bool("missing_incremented", comp_row_miss_inc)
    call trace_string("row_outcome", trim(outcome))
    call trace_end()
  end subroutine trace_hook_comp_c4

  subroutine emit_comp_c5_slots( &
      nbin, nb1, nbm_dim, hmaxshell_dim, freer_flag, nrefa, nrefm, &
      hnref_shell_work, hnref_shell_free, hnref_shell_obs, hnref_shell_all, &
      hperc_shell_refl)
    integer, intent(in) :: nbin, nb1, nbm_dim, hmaxshell_dim
    logical, intent(in) :: freer_flag
    integer, intent(in) :: nrefa(2, nbm_dim), nrefm(2, nbm_dim)
    integer, intent(in) :: hnref_shell_work(hmaxshell_dim), hnref_shell_free(hmaxshell_dim)
    integer, intent(in) :: hnref_shell_obs(hmaxshell_dim), hnref_shell_all(hmaxshell_dim)
    real, intent(in) :: hperc_shell_refl(hmaxshell_dim)

    integer(int32) :: ibin

    if (nb1 < 1) return

    do ibin = 1_int32, int(nb1, int32)
      call trace_begin("completeness_summary_slot")
      call trace_string("namespace", NS_COMPLETENESS)
      call trace_string("source_hook_id", "C5")
      call trace_int("call_id", int(comp_call_id, int32))
      call trace_int("NBIN", nbin)
      call trace_int("NB1", nb1)
      call trace_int("slot_index", ibin)
      call trace_bool("is_overall_slot", ibin == int(nb1, int32))
      call trace_bool("FREER_FLAG", freer_flag)
      call trace_int("NREFA_work", nrefa(1, ibin))
      call trace_int("NREFA_free", nrefa(2, ibin))
      call trace_int("NREFM_work", nrefm(1, ibin))
      call trace_int("NREFM_free", nrefm(2, ibin))
      call trace_int("HNREF_SHELL_WORK", hnref_shell_work(ibin))
      call trace_int("HNREF_SHELL_FREE", hnref_shell_free(ibin))
      call trace_int("HNREF_SHELL_OBS", hnref_shell_obs(ibin))
      call trace_int("HNREF_SHELL_ALL", hnref_shell_all(ibin))
      call trace_real("HPERC_SHELL_REFL", hperc_shell_refl(ibin))
      call trace_end()
    end do
  end subroutine emit_comp_c5_slots

  subroutine trace_hook_comp_c5_with_free( &
      nbin, nb1, nbm_dim, hmaxshell_dim, freer_flag, nrefa, nrefm, &
      hnref_shell_work, hnref_shell_free, hnref_shell_obs, hnref_shell_all, &
      hperc_shell_refl, nhrefl_work, nhrefl_free, perc_free)
    integer, intent(in) :: nbin, nb1, nbm_dim, hmaxshell_dim
    logical, intent(in) :: freer_flag
    integer, intent(in) :: nrefa(2, nbm_dim), nrefm(2, nbm_dim)
    integer, intent(in) :: hnref_shell_work(hmaxshell_dim), hnref_shell_free(hmaxshell_dim)
    integer, intent(in) :: hnref_shell_obs(hmaxshell_dim), hnref_shell_all(hmaxshell_dim)
    real, intent(in) :: hperc_shell_refl(hmaxshell_dim)
    integer, intent(in) :: nhrefl_work, nhrefl_free
    real, intent(in) :: perc_free

    if (.not. trace_is_enabled()) return

    call trace_begin("completeness_summary")
    call trace_string("namespace", NS_COMPLETENESS)
    call trace_string("source_hook_id", "C5")
    call trace_int("call_id", int(comp_call_id, int32))
    call trace_int("NBIN", nbin)
    call trace_int("NB1", nb1)
    call trace_bool("FREER_FLAG", freer_flag)
    call trace_int("NHREFL_WORK", nhrefl_work)
    call trace_int("NHREFL_FREE", nhrefl_free)
    call trace_real("PERC_FREE", perc_free)
    call trace_end()

    call emit_comp_c5_slots( &
      nbin, nb1, nbm_dim, hmaxshell_dim, freer_flag, nrefa, nrefm, &
      hnref_shell_work, hnref_shell_free, hnref_shell_obs, hnref_shell_all, &
      hperc_shell_refl)
  end subroutine trace_hook_comp_c5_with_free

  subroutine trace_hook_comp_c5_no_free( &
      nbin, nb1, nbm_dim, hmaxshell_dim, freer_flag, nrefa, nrefm, &
      hnref_shell_work, hnref_shell_free, hnref_shell_obs, hnref_shell_all, &
      hperc_shell_refl, nhrefl_work, perc_free)
    integer, intent(in) :: nbin, nb1, nbm_dim, hmaxshell_dim
    logical, intent(in) :: freer_flag
    integer, intent(in) :: nrefa(2, nbm_dim), nrefm(2, nbm_dim)
    integer, intent(in) :: hnref_shell_work(hmaxshell_dim), hnref_shell_free(hmaxshell_dim)
    integer, intent(in) :: hnref_shell_obs(hmaxshell_dim), hnref_shell_all(hmaxshell_dim)
    real, intent(in) :: hperc_shell_refl(hmaxshell_dim)
    integer, intent(in) :: nhrefl_work
    real, intent(in) :: perc_free

    if (.not. trace_is_enabled()) return

    call trace_begin("completeness_summary")
    call trace_string("namespace", NS_COMPLETENESS)
    call trace_string("source_hook_id", "C5")
    call trace_int("call_id", int(comp_call_id, int32))
    call trace_int("NBIN", nbin)
    call trace_int("NB1", nb1)
    call trace_bool("FREER_FLAG", freer_flag)
    call trace_int("NHREFL_WORK", nhrefl_work)
    call trace_real("PERC_FREE", perc_free)
    call trace_end()

    call emit_comp_c5_slots( &
      nbin, nb1, nbm_dim, hmaxshell_dim, freer_flag, nrefa, nrefm, &
      hnref_shell_work, hnref_shell_free, hnref_shell_obs, hnref_shell_all, &
      hperc_shell_refl)
  end subroutine trace_hook_comp_c5_no_free

  subroutine trace_hook_comp_c5( &
      nbin, nb1, nbm_dim, hmaxshell_dim, freer_flag, nrefa, nrefm, &
      hnref_shell_work, hnref_shell_free, hnref_shell_obs, hnref_shell_all, &
      hperc_shell_refl, nhrefl_work, nhrefl_free, perc_free)
    integer, intent(in) :: nbin, nb1, nbm_dim, hmaxshell_dim
    logical, intent(in) :: freer_flag
    integer, intent(in) :: nrefa(2, nbm_dim), nrefm(2, nbm_dim)
    integer, intent(in) :: hnref_shell_work(hmaxshell_dim), hnref_shell_free(hmaxshell_dim)
    integer, intent(in) :: hnref_shell_obs(hmaxshell_dim), hnref_shell_all(hmaxshell_dim)
    real, intent(in) :: hperc_shell_refl(hmaxshell_dim)
    integer, intent(in) :: nhrefl_work, nhrefl_free
    real, intent(in) :: perc_free

    if (freer_flag .and. nrefa(2, nb1) > 0) then
      call trace_hook_comp_c5_with_free( &
        nbin, nb1, nbm_dim, hmaxshell_dim, freer_flag, nrefa, nrefm, &
        hnref_shell_work, hnref_shell_free, hnref_shell_obs, hnref_shell_all, &
        hperc_shell_refl, nhrefl_work, nhrefl_free, perc_free)
    else
      call trace_hook_comp_c5_no_free( &
        nbin, nb1, nbm_dim, hmaxshell_dim, freer_flag, nrefa, nrefm, &
        hnref_shell_work, hnref_shell_free, hnref_shell_obs, hnref_shell_all, &
        hperc_shell_refl, nhrefl_work, perc_free)
    end if
  end subroutine trace_hook_comp_c5

  subroutine trace_hook_comp_c_end()
    if (comp_emitted_rows /= comp_expected_rows) then
      comp_defect_count = comp_defect_count + 1_int32
    end if

    if (trace_is_enabled()) then
      call trace_begin("completeness_end")
      call trace_string("namespace", NS_COMPLETENESS)
      call trace_string("source_hook_id", "C_end")
      call trace_int("call_id", int(comp_call_id, int32))
      call trace_int("expected_rows", comp_expected_rows)
      call trace_int("emitted_rows", comp_emitted_rows)
      call trace_bool("row_count_matches", comp_emitted_rows == comp_expected_rows)
      call trace_int("defect_count", comp_defect_count)
      call trace_end()
    end if

    comp_active = .false.
    comp_call_id = 0_int64
    comp_expected_rows = 0_int32
    comp_emitted_rows = 0_int32
    comp_defect_count = 0_int32
    comp_cur_row = 0_int32
  end subroutine trace_hook_comp_c_end

  subroutine trace_hook_normal_termination()
    if (.not. trace_is_enabled()) return

    call trace_begin("refmac_normal_termination")
    call trace_string("namespace", NS_LIFECYCLE)
    call trace_string("source_hook_id", "T_close")
    call trace_int("lsq_call_count", int(lsq_call_seq, int32))
    call trace_int("completeness_call_count", int(comp_call_seq, int32))
    call trace_bool("lsq_call_left_open", lsq_active)
    call trace_bool("completeness_call_left_open", comp_active)
    call trace_end()

    call trace_close()
  end subroutine trace_hook_normal_termination

end module protstruct_diagnostic_hooks
