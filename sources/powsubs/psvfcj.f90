 Module Profile_Finger
    !    Here the functions provided in the original code by L. Finger have been
    !    implemented as subroutines as is the common practice in Fortran 90 when
    !    several dummy arguments have output intent attribute.
    !    The subroutine Prof_Val returns the value of the profile function at twoth of
    !    a peak of centre twoth0 as well as the derivatives wrt profile parameters.
    !    Asymmetry due to axial divergence using the method of Finger, Cox and Jephcoat,
    !    J. Appl. Cryst. 27, 892, 1992.
    !    This version based on code provided by Finger, Cox and Jephcoat as modified
    !    by J Hester (J. Appl. Cryst. (2013),46,1219-1220)
    !    with a new derivative calculation method and then optimised,
    !    adapted to Fortran 90 and further improved by J. Rodriguez-Carvajal.
    !    Further changed by J. Hester to include optimisations found in GSAS-II version
    !    of original FCJ code, and streamlined for incorporation into GSAS-II
   
    IMPLICIT NONE

    !---- LIST OF PUBLIC SUBROUTINES ----!
    PUBLIC :: PROF_VAL

    !---- LIST OF PRIVATE FUNCTIONS ----!
    PRIVATE ::  DFUNC_INT, EXTRA_INT

    INTEGER,       PARAMETER :: SP = SELECTED_REAL_KIND(6,30)
    INTEGER,       PARAMETER :: DP = SELECTED_REAL_KIND(14,150)
    INTEGER,       PARAMETER :: CP = SP    !SWITCH TO DOUBLE PRECISION BY PUTTING CP=DP
    REAL(KIND=DP), PARAMETER :: PI = 3.141592653589793238463_DP
    REAL(KIND=DP), PARAMETER :: TO_DEG  = 180.0_DP/PI
    REAL(KIND=DP), PARAMETER :: TO_RAD  = PI/180.0_DP
    INTEGER,       PARAMETER :: NUMTAB = 34
    INTEGER, PRIVATE,DIMENSION(NUMTAB) :: NTERMS =(/2,4,6,8,10,12,14,16,18,20,22,24,26,28, &
         30,40,50,60,70,80,90,100,110,120,140,160,180,200,220,240,260,280,300,400/)
    INTEGER, PRIVATE,DIMENSION(NUMTAB) :: FSTTERM=(/0,1,3,6,10,15,21,28,36,45,55,66,78, &
         91,105,120,140,165,195,230,270,315,365,420,480,550,630, &
         720,820,930,1050,1180,1320,1470/) !FSTTERM(1) SHOULD BE ZERO, INDEXING STARTS AT 1+ THIS NUMBER
    REAL(KIND=CP),PRIVATE,DIMENSION(0:1883) :: WP  !EXTRA SPACE FOR EXPANSION
    REAL(KIND=CP),PRIVATE,DIMENSION(0:1883) :: XP  !EXTRA SPACE FOR EXPANSION

    !
    ! VARIABLES TO SWITCH TO NEW CALCULATIONS OF SOME VARIABLES THAT DEPEND
    ! ONLY ON (TWOTH0,ASYM1,ASYM2) AND NOT ON THE PARTICULAR POINT OF THE PROFILE.
    ! WHEN THE SUBROUTINE IS INVOKED FOR THE SAME REFLECTION SOME VARIABLES
    ! ARE NOT CALCULATED.
    !
    !
    REAL(KIND=CP), PRIVATE, SAVE :: TWOTH0_PREV = 0.0_CP
    REAL(KIND=CP), PRIVATE, SAVE ::  ASYM1_PREV = 0.0_CP
    REAL(KIND=CP), PRIVATE, SAVE ::  ASYM2_PREV = 0.0_CP

    ! FIXED CONSTANTS
    REAL(KIND=CP), PRIVATE, PARAMETER :: PI_OVER_TWO=0.5_CP*PI
    REAL(KIND=CP), PRIVATE, PARAMETER :: EPS=1.0E-6_CP
    ! FOLLOWING GIVES THE NOTIONAL NUMBER OF STEPS PER DEGREE FOR QUADRATURE
    INTEGER,       PRIVATE, PARAMETER :: CTRL_NSTEPS= 300
    LOGICAL,       PRIVATE, DIMENSION(NUMTAB) :: CALCLFG
    !CALCLFG TRUE IF TABLE ENTRY CALCULATED
    DATA CALCLFG/NUMTAB*.FALSE./
 CONTAINS

    SUBROUTINE PROF_VAL( SIG, GAMMA, ASYM1, ASYM2, TWOTH, TWOTH0, DPRDT, DPRDG,  &
         DPRDLZ , DPRDS , DPRDD , PROFVAL)
      REAL(KIND=CP), INTENT(IN)    :: SIG        ! GAUSSIAN VARIANCE (I.E. SIG SQUARED)
      REAL(KIND=CP), INTENT(IN)    :: GAMMA      ! LORENZIAN FWHM (I.E. 2 HWHM)
      REAL(KIND=CP), INTENT(IN)    :: ASYM1      ! D_L+S_L
      REAL(KIND=CP), INTENT(IN)    :: ASYM2      ! D_L-S_L
      REAL(KIND=CP), INTENT(IN)    :: TWOTH      ! POINT AT WHICH TO EVALUATE THE PROFILE
      REAL(KIND=CP), INTENT(IN)    :: TWOTH0     ! TWO_THETA VALUE FOR PEAK
      REAL(KIND=CP), INTENT(OUT)   :: DPRDT      ! DERIVATIVE OF PROFILE WRT TWOTH0
      REAL(KIND=CP), INTENT(OUT)   :: DPRDG      ! DERIVATIVE OF PROFILE WRT GAUSSIAN SIG
      REAL(KIND=CP), INTENT(OUT)   :: DPRDLZ     ! DERIVATIVE OF PROFILE WRT LORENZIAN
      REAL(KIND=CP), INTENT(OUT)   :: DPRDS      ! DERIVATIVE OF PROFILE WRT ASYM1
      REAL(KIND=CP), INTENT(OUT)   :: DPRDD      ! DERIVATIVE OF PROFILE WRT ASYM2
      REAL(KIND=CP), INTENT(OUT)   :: PROFVAL    ! VALUE OF THE PROFILE AT POINT TWOTH
      !THE VARIABLES BELOW HAVE THE "SAVE" ATTRIBUTE IN ORDER TO SAVE CALCULATION
      !TIME WHEN THE SUBROUTINE IS INVOKED FOR DIFFERENT POINTS OF THE SAME PEAK
      REAL(KIND=CP),SAVE :: S_L , D_L, HALF_OVER_DL
      REAL(KIND=CP),SAVE :: DF_DH_FACTOR, DF_DS_FACTOR
      REAL(KIND=CP),SAVE :: DFI_EMIN, DFI_EINFL
      REAL(KIND=CP),SAVE :: NORMV_ANALYTIC
      REAL(KIND=CP),SAVE :: EINFL              ! 2PHI VALUE FOR INFLECTION POINT
      REAL(KIND=CP),SAVE :: EMIN               ! 2PHI VALUE FOR MINIMUM
      REAL(KIND=CP),SAVE :: CSTWOTH            ! COS(TWOTH)
      REAL(KIND=CP),SAVE :: COSEINFL           ! COS(EINFL)
      REAL(KIND=CP),SAVE :: APB                ! (S + H)/L
      REAL(KIND=CP),SAVE :: AMB                ! (S - H)/L
      REAL(KIND=CP),SAVE :: APB2               ! (APB) **2
      INTEGER,SAVE       :: ARRAYNUM, NGT, NGT2, IT
      LOGICAL,SAVE       :: S_EQ_D
      

      ! VARIABLES NOT CONSERVING THEIR VALUE BETWEEN CALLS
      INTEGER       :: SIDE, K
      REAL(KIND=CP) :: TMP , TMP1 , TMP2  ! INTERMEDIATE VALUES
      REAL(KIND=CP) :: DELTA              ! ANGLE OF INTEGRATION FOR COMVOLUTION
      REAL(KIND=CP) :: SINDELTA           ! SINE OF DELTA
      REAL(KIND=CP) :: COSDELTA           ! COSINE OF DELTA
      REAL(KIND=CP) :: RCOSDELTA          ! 1/COS(DELTA)
      REAL(KIND=CP) :: F,G, EINFLR,EMINR,TWOTH0R
      REAL(KIND=CP) :: SUMWG, SUMWRG, SUMWRDGDA ,SUMWDGDB , SUMWRDGDB
      REAL(KIND=CP) :: SUMWGDRDG, SUMWGDRDLZ, SUMWGDRD2T
      REAL(KIND=CP) :: SUMWX
      REAL(KIND=CP) :: XPT(1000)          !TEMPORARY STORAGE
      REAL(KIND=CP) :: WPT(1000)          !TEMPORARY STORAGE
      LOGICAL       :: RE_CALCULATE

      ! FIRST SIMPLE CALCULATION OF PSEUDO-VOIGT IF ASYMMETRY IS NOT USED
      IF(ASYM1 == 0.0) THEN
        CALL PSVOIGT(TWOTH-TWOTH0,SIG,GAMMA,TMP,TMP1,DPRDG,DPRDLZ)
        PROFVAL = TMP
        DPRDS = 0.4*SIGN(1.0,2.0*TWOTH0-TWOTH)
        DPRDD = 0.0
        DPRDT = -TMP1    !DERIVATIVE RELATIVE TO CENTRE POSITION
        RETURN
      END IF

      !FROM HERE TO THE END OF THE PROCEDURE ASYMMETRY IS USED.
      !MAKE THE CALCULATIONS OF SOME VARIABLES ONLY IF TWOTH0,ASYM1,ASYM2
      !ARE DIFFERENT FROM PREVIOUS VALUES. THIS SAVES CALCULATION TIME IF THE
      !DIFFERENT POINTS OF A PEAK ARE CALCULATED SEQUENTIALLY FOR THE SAME VALUES
      !OF TWOTHETA AND ASYMMETRY PARAMETERS.

      RE_CALCULATE= ABS(TWOTH0_PREV-TWOTH0) > EPS .OR.  &
                    ABS(ASYM1_PREV-ASYM1)   > EPS .OR.  &
                    ABS(ASYM2_PREV-ASYM2)   > EPS

      IF(RE_CALCULATE) THEN
        TWOTH0_PREV=TWOTH0
         ASYM1_PREV=ASYM1
         ASYM2_PREV=ASYM2

        TWOTH0R=TWOTH0*TO_RAD
        CSTWOTH = COS(TWOTH0R)
        S_L = 0.5*(ASYM1 - ASYM2)  ! 1/2(S_L+D_L - (D_L-S_L))
        D_L = 0.5*(ASYM1 + ASYM2)  ! 1/2(S_L+D_L + (D_L-S_L))
        APB = ASYM1
        AMB = ASYM2
        ! CATCH SPECIAL CASE OF S_L = D_L
        IF (ABS(AMB) < 0.00001) THEN
          S_EQ_D = .TRUE.
        ELSE
          S_EQ_D = .FALSE.
        END IF
        APB2 = APB*APB

        TMP = SQRT(1.0 + AMB*AMB)*CSTWOTH
        IF ((ABS(TMP) > 1.0) .OR. (ABS(TMP) <= ABS(CSTWOTH))) THEN
          EINFL = TWOTH0
          EINFLR=EINFL*TO_RAD
          DFI_EINFL = PI_OVER_TWO
        ELSE
          EINFLR = ACOS(TMP)
          EINFL=EINFLR*TO_DEG
          DFI_EINFL = DFUNC_INT(EINFLR,TWOTH0R)
        END IF
        COSEINFL = COS(EINFLR)
        TMP2 = 1.0 + APB2
        TMP = SQRT(TMP2) * CSTWOTH

        ! IF S_L OR D_L ARE ZERO, SET EINFL = 2THETA
        ! IF S_L EQUALS D_L, SET EINFL = 2THETA

        IF ((S_L == 0.0) .OR. (D_L == 0.0) .OR. S_EQ_D) THEN
          EINFL = TWOTH0
          EINFLR=EINFL*TO_RAD
        END IF

        IF (ABS(TMP) <= 1.0) THEN
          EMINR = ACOS(TMP)
          EMIN = EMINR * TO_DEG
          TMP1 = TMP2 * (1.0 - TMP2 * CSTWOTH*CSTWOTH)
        ELSE
          TMP1 = 0.0
          IF (TMP > 0.0) THEN
            EMIN = 0.0
            EMINR= 0.0
          ELSE
            EMIN = 180.0
            EMINR= PI
          END IF
        END IF

        DFI_EMIN = DFUNC_INT(EMINR,TWOTH0R)
        !
        ! SIMPLIFICATIONS IF S_L EQUALS D_L
        !
        HALF_OVER_DL=0.5_CP/D_L
        IF (S_EQ_D) THEN
          DFI_EINFL = PI_OVER_TWO
          NORMV_ANALYTIC = (PI_OVER_TWO - DFI_EMIN)  &
              - 2.0_CP*HALF_OVER_DL*(EXTRA_INT(EINFLR)-EXTRA_INT(EMINR))
          DF_DH_FACTOR =  HALF_OVER_DL * (PI_OVER_TWO - DFI_EMIN)
          DF_DS_FACTOR =  HALF_OVER_DL * (PI_OVER_TWO - DFI_EMIN)
          DF_DH_FACTOR = DF_DH_FACTOR - 2.0_CP*HALF_OVER_DL * NORMV_ANALYTIC
        ELSE
          DFI_EINFL = DFUNC_INT(EINFLR,TWOTH0R)
          NORMV_ANALYTIC = MIN(S_L,D_L)/D_L*(PI_OVER_TWO - DFI_EINFL)
          NORMV_ANALYTIC = NORMV_ANALYTIC + APB*HALF_OVER_DL*(DFI_EINFL-DFI_EMIN)   &
                       - 2.0_CP*HALF_OVER_DL*(EXTRA_INT(EINFLR)-EXTRA_INT(EMINR))
          TMP= HALF_OVER_DL*(PI - DFI_EINFL - DFI_EMIN)
          TMP1=HALF_OVER_DL*(DFI_EINFL - DFI_EMIN)
          IF(D_L < S_L) THEN
            DF_DH_FACTOR = TMP
            DF_DS_FACTOR = TMP1
          ELSE
            DF_DH_FACTOR = TMP1
            DF_DS_FACTOR = TMP
          END IF
          DF_DH_FACTOR = DF_DH_FACTOR - 2.0_CP*HALF_OVER_DL * NORMV_ANALYTIC
        END IF
        ARRAYNUM = 1
        ! NUMBER OF TERMS NEEDED, GSAS-II FORMULATION
        TMP = ABS(TWOTH0 - EMIN)
        IF (GAMMA <= 0.0) THEN
           K = CTRL_NSTEPS*TMP/2
        ELSE
           K = CTRL_NSTEPS*TMP/(100*GAMMA)
        ENDIF
        DO
           IF ( .NOT. ( ARRAYNUM < NUMTAB  .AND.  K > NTERMS(ARRAYNUM) ) ) EXIT
           ARRAYNUM = ARRAYNUM + 1
        END DO
        NGT = NTERMS(ARRAYNUM)              ! SAVE THE NUMBER OF TERMS
        NGT2 = NGT / 2
        ! CALCULATE GAUSS-LEGENDRE QUADRATURE TERMS THE FIRST TIME THEY
        ! ARE REQUIRED
        IF (.NOT. CALCLFG(ARRAYNUM)) THEN
           CALCLFG(ARRAYNUM) = .TRUE.
           CALL GAULEG(-1.,1.,XPT,WPT,NGT)
           IT = FSTTERM(ARRAYNUM)-NGT2
           !
           ! COPY THE NGT/2 TERMS FROM OUR WORKING ARRAY TO THE STORED ARRAY
           !
           DO K=NGT2+1,NGT
              XP(K+IT) = XPT(K)
              WP(K+IT) = WPT(K)
           ENDDO
      END IF
      IT = FSTTERM(ARRAYNUM)-NGT2  !IN CASE SKIPPED INITIALISATION

   END IF   !RE_CALCULATE
        ! CLEAR TERMS NEEDED FOR SUMMATIONS
      SUMWG = 0.0
      SUMWRG = 0.0
      SUMWRDGDA = 0.0
      SUMWDGDB = 0.0
      SUMWRDGDB = 0.0
      SUMWGDRD2T = 0.0
      SUMWGDRDG = 0.0
      SUMWGDRDLZ = 0.0
      SUMWX = 0.0
      ! COMPUTE THE CONVOLUTION INTEGRAL WITH THE PSEUDOVOIGHT.
      ! USING GAUSS-LEGENDRE QUADRATURE.
      ! IN THEORY, WE SHOULD USE THE WEIGHTED W_I VALUES OF THE
      ! PRODUCT OF THE ASYMMETRY
      ! PROFILE WITH THE PSEUDOVOIGHT AT A SET OF POINTS X_I IN THE
      ! INTERVAL [-1,1]. HOWEVER, 
      ! THE FOLLOWING ADOPTS THE GSAS-II APPROACH OF INSTEAD INTEGRATING
      ! BETWEEN 0 AND 1, WHICH CAN BE IMAGINED AS EXTENDING THE RANGE
      ! OF INTEGRATION BE FROM EMIN - TWOTH0 UP TO TWOTH0.
      ! THIS SEEMS TO BE PREFERABLE BECAUSE THE MOST IMPORTANT AREA
      ! FOR INTEGRATION IS THE RAPIDLY INCREASING PEAK, AND SO THE
      ! HIGHER DENSITY OF POINTS AT THE END OF THE INTERVAL WORKS IN OUR
      ! FAVOUR.
      DO K = NGT2+1 , NGT
          DELTA = EMIN + (TWOTH0 - EMIN) * XP(K + IT)
          SINDELTA = SIN(DELTA*TO_RAD)
          COSDELTA = COS(DELTA*TO_RAD)
          IF (ABS(COSDELTA) < 1.0E-15) COSDELTA = 1.0E-15
          RCOSDELTA = ABS(1.0 / COSDELTA)
          TMP = COSDELTA*COSDELTA - CSTWOTH*CSTWOTH
          IF (TMP > 0.0) THEN
            TMP1 = SQRT(TMP)
            F = ABS(CSTWOTH) / TMP1           !H-FUNCTION IN FCJ
          ELSE
            F = 0.0
          END IF
          !  CALCULATE G(DELTA,2THETA) , FCJ EQ. 7A AND 7B
          IF ( ABS(DELTA - EMIN) > ABS(EINFL - EMIN)) THEN
            IF (S_L > D_L) THEN
              G = 2.0 * D_L * F * RCOSDELTA
            ELSE
              G = 2.0 * S_L * F * RCOSDELTA
            END IF
          ELSE
            G = (-1.0 + APB * F) * RCOSDELTA
          END IF
          CALL PSVOIGT(TWOTH-DELTA,SIG,GAMMA,TMP,DPRDT,DPRDG,DPRDLZ)
          SUMWG = SUMWG + WP(K+IT) * G
          SUMWRG = SUMWRG + WP(K+IT) * G * TMP
          IF ( ABS(COSDELTA) > ABS(COSEINFL)) THEN
            SUMWRDGDA = SUMWRDGDA + WP(K+IT) * F * RCOSDELTA * TMP
            SUMWRDGDB = SUMWRDGDB + WP(K+IT) * F * RCOSDELTA * TMP
          ELSE
            IF (S_L < D_L) THEN
              SUMWRDGDB = SUMWRDGDB + 2.0*WP(K+IT)*F* RCOSDELTA*TMP
            ELSE
              SUMWRDGDA = SUMWRDGDA + 2.0*WP(K+IT)*F* RCOSDELTA*TMP
            END IF
          END IF
          SUMWGDRD2T = SUMWGDRD2T + WP(K+IT) * G * DPRDT
          SUMWGDRDG = SUMWGDRDG + WP(K+IT) * G * DPRDG
          SUMWGDRDLZ = SUMWGDRDLZ + WP(K+IT) * G * DPRDLZ
      END DO

      IF (SUMWG == 0.0) SUMWG = 1.0_CP
      PROFVAL = SUMWRG / SUMWG
      ! MINUS SIGN IN FOLLOWING AS PSVOIGHT RETURNS DERIVS AGAINST X, NOT
      ! AGAINST THE CENTRE POSITION.
      DPRDT = -SUMWGDRD2T/ SUMWG
      DPRDG = SUMWGDRDG / SUMWG
      DPRDLZ = SUMWGDRDLZ / SUMWG
      !
      IF(NORMV_ANALYTIC <= 0.0) NORMV_ANALYTIC=1.0_CP
      DPRDD = SUMWRDGDA / SUMWG - DF_DH_FACTOR*PROFVAL/NORMV_ANALYTIC - PROFVAL/D_L
      DPRDS = SUMWRDGDB / SUMWG - DF_DS_FACTOR*PROFVAL/NORMV_ANALYTIC

      DPRDS = 0.5_CP*(DPRDD + DPRDS)  !S IS REALLY D+S
      DPRDD = 0.5_CP*(DPRDD - DPRDS)  !D IS REALLY D-S
      RETURN
    END SUBROUTINE PROF_VAL

!  FUNCTION TO GIVE THE ANALYTICAL VALUE OF THE NORMALISATION CONSTANT

    FUNCTION DFUNC_INT(TWOPSI, TWOTH0) RESULT(DFUNC)
      REAL(KIND=CP), INTENT(IN)  :: TWOPSI
      REAL(KIND=CP), INTENT(IN)  :: TWOTH0
      REAL(KIND=CP)              :: DFUNC
      !--- LOCAL VARIABLES
      REAL(KIND=CP) :: SINTP        !SIN TWOPSI
      REAL(KIND=CP) :: SIN2T,SIN2T2,CSP,CSM,SSP,SSM,A,B ! SIN2THETA, (SIN2THETA)^2

      IF(ABS(TWOPSI-TWOTH0) < 1.0E-5) THEN
        DFUNC=PI_OVER_TWO
      ELSE
        SIN2T=SIN(TWOTH0)
        SIN2T2=SIN2T*SIN2T
        SINTP = SIN(TWOPSI)
        CSP=SINTP+SIN2T2
        CSM=SINTP-SIN2T2
        SSP=ABS((SINTP+1.0_CP)*SIN2T)
        SSM=ABS((SINTP-1.0_CP)*SIN2T)
        A=CSM/SSM; B=-CSP/SSP
        IF(A > 1.0_CP) A=1.0_CP
        IF(B <-1.0_CP) B=-1.0_CP
        DFUNC=0.5_CP*(ASIN(A)-ASIN(B))
      END IF
    END FUNCTION DFUNC_INT

    !  FUNCTION TO CALCULATE 1/4(LOG(|SIN(X)+1|)-LOG(|SIN(X)-1|))
    FUNCTION EXTRA_INT(X) RESULT(EXTRA)
      REAL(KIND=CP), INTENT(IN) :: X
      REAL(KIND=CP)             :: EXTRA
      !--- LOCAL VARIABLES
      REAL(KIND=CP)             :: SINX

      SINX = SIN(X)
      EXTRA = 0.25_CP*(LOG(ABS(SINX+1.0_CP))-LOG(ABS(SINX-1.0_CP)))
    END FUNCTION EXTRA_INT

END MODULE PROFILE_FINGER

! LINKAGE FOR F2PY AS DIRECT CALLING OF FORTRAN MODULE CONTENTS
! FROM OUTSIDE FILE CONTAINING MODULE FAILS WHEN SEPARATE OBJECT FILES COMBINED INTO
! SINGLE PYTHON LOADABLE MODULE
SUBROUTINE GET_PROF_VAL( SIG, GAMMA, ASYM1, ASYM2, TWOTH, TWOTH0, DPRDT, DPRDG,  &
     DPRDLZ , DPRDS , DPRDD , PROFVAL)
  USE PROFILE_FINGER, ONLY:PROF_VAL
      INTEGER,       PARAMETER :: SP = SELECTED_REAL_KIND(6,30)
      INTEGER,       PARAMETER :: DP = SELECTED_REAL_KIND(14,150)
      INTEGER,       PARAMETER :: CP = SP    !SWITCH TO DOUBLE PRECISION BY PUTTING CP=DP
      REAL(KIND=CP), INTENT(IN)    :: SIG        ! GAUSSIAN VARIANCE (I.E. SIG SQUARED)
      REAL(KIND=CP), INTENT(IN)    :: GAMMA      ! LORENZIAN FWHM (I.E. 2 HWHM)
      REAL(KIND=CP), INTENT(IN)    :: ASYM1      ! D_L+S_L
      REAL(KIND=CP), INTENT(IN)    :: ASYM2      ! D_L-S_L
      REAL(KIND=CP), INTENT(IN)    :: TWOTH      ! POINT AT WHICH TO EVALUATE THE PROFILE
      REAL(KIND=CP), INTENT(IN)    :: TWOTH0     ! TWO_THETA VALUE FOR PEAK
      REAL(KIND=CP), INTENT(OUT)   :: DPRDT      ! DERIVATIVE OF PROFILE WRT TWOTH0
      REAL(KIND=CP), INTENT(OUT)   :: DPRDG      ! DERIVATIVE OF PROFILE WRT GAUSSIAN SIG
      REAL(KIND=CP), INTENT(OUT)   :: DPRDLZ     ! DERIVATIVE OF PROFILE WRT LORENZIAN
      REAL(KIND=CP), INTENT(OUT)   :: DPRDS      ! DERIVATIVE OF PROFILE WRT ASYM1
      REAL(KIND=CP), INTENT(OUT)   :: DPRDD      ! DERIVATIVE OF PROFILE WRT ASYM2
      REAL(KIND=CP), INTENT(OUT)   :: PROFVAL    ! VALUE OF THE PROFILE AT POINT TWOTH
      CALL PROF_VAL(SIG,GAMMA,ASYM1,ASYM2,TWOTH,TWOTH0,DPRDT,DPRDG,DPRDLZ,DPRDS, &
           DPRDD,PROFVAL)
      RETURN
    END SUBROUTINE GET_PROF_VAL


