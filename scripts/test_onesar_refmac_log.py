#!/usr/bin/env python3
"""Hermetic unit tests for scripts/onesar_refmac_log.py.

All fixtures in this test suite are self-contained in-memory strings with
explicit provenance labels (historical AMPLE REFMAC 5.8.0049 source excerpt
and synthetic test cases). No installed vendor tools, external files, or
network access are required.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from onesar_refmac_log import parse_refmac_log  # noqa: E402


# Provenance: Verbatim structural excerpt from the historical AMPLE test fixture
# (`ccp4-9/share/ample/testfiles/refmac.log`, SHA-256
# 15593c60819187660ab7a267ed0232a67bb016262619de06bf56644378df2c2a,
# CCP4 6.4 / REFMAC 5.8.0049, run date 15/ 7/2014, input 1BYZ-cad.mtz, NCYC 30).
# Used strictly as parser-shape evidence, never as 1SAR or current-tool evidence.
HISTORICAL_AMPLE_EXCERPT_LOG = """\
<html> <!-- CCP4 HTML LOGFILE -->
<pre>
 ### CCP4 6.4: Refmac_5.8.0049     version 5.8.0049 : 30/06/13##
 User: unknown  Run date: 15/ 7/2014 Run time: 21:14:02 
 $TEXT:Reference1: $$ Main reference $$ 
   "REFMAC5 for the refinement of macromolecular crystal structures:"
 $$
 $SUMMARY :Reference1:  $$ Refmac: $$
 :TEXT:Reference1: $$
  Data line--- LABIN FP=FP SIGFP=SIGFP FREE=FREE
  Data line--- NCYC 30
  Data line--- END
  Refinement cycles       :    30

$TABLE: Cycle    1. Rfactor analysis, F distribution v resln  :
$GRAPHS:Cycle    1. <Rfactor> v. resln :N:1,6,7,11,12:
:Cycle    1. <Fobs> and <Fc> v. resln :N:1,4,5,9,10:
:Cycle    1. % observed v. resln :N:1,3:
$$
M(4SSQ/LL) NR_used %_obs M(Fo_used) M(Fc_used) Rf_used WR_used
NR_free M(Fo_free) M(Fc_free) Rf_free   WR_free $$
$$
 0.032     293  99.36    39.1    31.2  0.54  0.77      19    24.6    36.2  0.76  1.48
 0.093     548 100.00    35.1    25.7  0.53  0.61      35    32.9    26.5  0.53  0.59
 0.154     675 100.00    28.2    23.8  0.51  0.62      35    23.7    21.4  0.58  0.70
 0.215     853 100.00    23.6    18.9  0.55  0.65      39    25.4    18.8  0.54  0.59
 0.276     920 100.00    18.0    14.4  0.55  0.60      48    16.2    13.9  0.47  0.55
 0.338    1031 100.00    14.7    11.9  0.51  0.54      70    13.6    11.4  0.51  0.53
 0.399    1106 100.00    13.4     9.9  0.55  0.55      68    13.1    10.1  0.45  0.45
 0.460    1193 100.00    12.3     9.5  0.52  0.54      68    10.4     9.3  0.45  0.47
 0.521    1279  99.85    10.5     8.3  0.55  0.55      72    10.8     8.7  0.46  0.48
 0.582    1356  99.72    10.0     8.0  0.53  0.52      75    11.8     7.8  0.58  0.58
 0.643    1364  99.18     9.8     7.6  0.55  0.55      82     9.2     7.2  0.52  0.53
 0.704    1473  98.72     9.1     6.8  0.55  0.54      70     9.7     6.5  0.56  0.54
 0.765    1546  97.89     8.9     6.3  0.56  0.56      79     8.0     5.8  0.55  0.53
 0.826    1484  92.33     7.9     5.9  0.54  0.53      82     8.0     5.9  0.55  0.52
 0.887    1434  87.55     7.5     5.5  0.55  0.53      85     7.6     5.1  0.57  0.54
 0.948    1468  82.59     6.5     4.9  0.54  0.52      50     5.7     5.3  0.45  0.43
 1.010    1351  75.18     5.4     4.1  0.57  0.54      73     4.7     4.5  0.64  0.60
 1.071    1200  67.16     4.4     3.5  0.57  0.56      70     4.2     3.8  0.53  0.50
 1.132    1143  58.99     3.9     3.0  0.53  0.53      51     3.5     3.0  0.57  0.60
 1.193     750  39.07     3.8     2.6  0.53  0.54      42     3.9     2.5  0.51  0.53
$$

 $TABLE: Cycle    1. Fom(<cos(DelPhi)>-acentric, centric, overall v resln:
 $GRAPHS:Cycle    1. M(Fom) v. resln :N:1,3,5,7,8:
 $$
 <4SSQ/LL> NREFa  FOMa  NREFc FOMc NREFall FOMall  SigmaA_Fc1 $$
 $$
  0.0321   293   0.567     0   0.000   293   0.567  0.646
  0.0932   548   0.567     0   0.000   548   0.567  0.658
  0.1542   675   0.572     0   0.000   675   0.572  0.667
  0.2153   853   0.511     0   0.000   853   0.511  0.675
  0.2764   920   0.442     0   0.000   920   0.442  0.681
  0.3375  1031   0.422     0   0.000  1031   0.422  0.693
  0.3986  1106   0.447     0   0.000  1106   0.447  0.729
  0.4597  1193   0.483     0   0.000  1193   0.483  0.721
  0.5208  1279   0.316     0   0.000  1279   0.316  0.524
  0.5819  1356   0.246     0   0.000  1356   0.246  0.430
  0.6430  1364   0.282     0   0.000  1364   0.282  0.529
  0.7041  1473   0.307     0   0.000  1473   0.307  0.580
  0.7652  1546   0.333     0   0.000  1546   0.333  0.574
  0.8262  1484   0.270     0   0.000  1484   0.270  0.489
  0.8873  1434   0.219     0   0.000  1434   0.219  0.410
  0.9484  1468   0.304     0   0.000  1468   0.304  0.537
  1.0095  1351   0.409     0   0.000  1351   0.409  0.642
  1.0706  1200   0.256     0   0.000  1200   0.256  0.445
  1.1317  1143   0.279     0   0.000  1143   0.279  0.478
  1.1928   750   0.193     0   0.000   750   0.193  0.361
 $$
Resolution limits                    =     25.690     0.904
Number of used reflections           =      22467
Percentage observed                  =    85.8624
Percentage of free reflections       =     5.1225
Overall R factor                     =     0.5397
Free R factor                        =     0.5317
Overall weighted R factor            =     0.5603
Free weighted R factor               =     0.5489
Overall weighted R2 factor           =     0.7148
Free weighted R2 factor              =     0.7169
Overall figure of merit              =     0.3465
-----------------------------------------------------------------------------
Overall R factor                     =     0.5380
Free R factor                        =     0.5313
Overall figure of merit              =     0.3343
-----------------------------------------------------------------------------
Overall R factor                     =     0.5363
Free R factor                        =     0.5315
Overall figure of merit              =     0.3314
-----------------------------------------------------------------------------
Overall R factor                     =     0.5352
Free R factor                        =     0.5321
Overall figure of merit              =     0.3295
-----------------------------------------------------------------------------
Overall R factor                     =     0.5344
Free R factor                        =     0.5327
Overall figure of merit              =     0.3301
-----------------------------------------------------------------------------
Overall R factor                     =     0.5338
Free R factor                        =     0.5330
Overall figure of merit              =     0.3294
-----------------------------------------------------------------------------
Overall R factor                     =     0.5334
Free R factor                        =     0.5333
Overall figure of merit              =     0.3285
-----------------------------------------------------------------------------
Overall R factor                     =     0.5330
Free R factor                        =     0.5336
Overall figure of merit              =     0.3282
-----------------------------------------------------------------------------
Overall R factor                     =     0.5327
Free R factor                        =     0.5339
Overall figure of merit              =     0.3273
-----------------------------------------------------------------------------
Overall R factor                     =     0.5324
Free R factor                        =     0.5343
Overall figure of merit              =     0.3269
-----------------------------------------------------------------------------
Overall R factor                     =     0.5322
Free R factor                        =     0.5344
Overall figure of merit              =     0.3259
-----------------------------------------------------------------------------
Overall R factor                     =     0.5319
Free R factor                        =     0.5345
Overall figure of merit              =     0.3246
-----------------------------------------------------------------------------
Overall R factor                     =     0.5315
Free R factor                        =     0.5345
Overall figure of merit              =     0.3239
-----------------------------------------------------------------------------
Overall R factor                     =     0.5311
Free R factor                        =     0.5345
Overall figure of merit              =     0.3235
-----------------------------------------------------------------------------
Overall R factor                     =     0.5307
Free R factor                        =     0.5346
Overall figure of merit              =     0.3237
-----------------------------------------------------------------------------
Overall R factor                     =     0.5302
Free R factor                        =     0.5342
Overall figure of merit              =     0.3226
-----------------------------------------------------------------------------
Overall R factor                     =     0.5297
Free R factor                        =     0.5338
Overall figure of merit              =     0.3219
-----------------------------------------------------------------------------
Overall R factor                     =     0.5291
Free R factor                        =     0.5331
Overall figure of merit              =     0.3213
-----------------------------------------------------------------------------
Overall R factor                     =     0.5283
Free R factor                        =     0.5326
Overall figure of merit              =     0.3222
-----------------------------------------------------------------------------
Overall R factor                     =     0.5274
Free R factor                        =     0.5321
Overall figure of merit              =     0.3225
-----------------------------------------------------------------------------
Overall R factor                     =     0.5265
Free R factor                        =     0.5316
Overall figure of merit              =     0.3227
-----------------------------------------------------------------------------
Overall R factor                     =     0.5258
Free R factor                        =     0.5308
Overall figure of merit              =     0.3233
-----------------------------------------------------------------------------
Overall R factor                     =     0.5251
Free R factor                        =     0.5301
Overall figure of merit              =     0.3232
-----------------------------------------------------------------------------
Overall R factor                     =     0.5245
Free R factor                        =     0.5295
Overall figure of merit              =     0.3256
-----------------------------------------------------------------------------
Overall R factor                     =     0.5239
Free R factor                        =     0.5291
Overall figure of merit              =     0.3288
-----------------------------------------------------------------------------
Overall R factor                     =     0.5234
Free R factor                        =     0.5287
Overall figure of merit              =     0.3318
-----------------------------------------------------------------------------
Overall R factor                     =     0.5228
Free R factor                        =     0.5287
Overall figure of merit              =     0.3347
-----------------------------------------------------------------------------
Overall R factor                     =     0.5222
Free R factor                        =     0.5286
Overall figure of merit              =     0.3394
-----------------------------------------------------------------------------
Overall R factor                     =     0.5217
Free R factor                        =     0.5286
Overall figure of merit              =     0.3400
-----------------------------------------------------------------------------
Overall R factor                     =     0.5211
Free R factor                        =     0.5288
Overall figure of merit              =     0.3401
-----------------------------------------------------------------------------

$TABLE: Cycle   31. Rfactor analysis, F distribution v resln  :
$GRAPHS:Cycle   31. <Rfactor> v. resln :N:1,6,7,11,12:
:Cycle   31. <Fobs> and <Fc> v. resln :N:1,4,5,9,10:
:Cycle   31. % observed v. resln :N:1,3:
$$
M(4SSQ/LL) NR_used %_obs M(Fo_used) M(Fc_used) Rf_used WR_used
NR_free M(Fo_free) M(Fc_free) Rf_free   WR_free $$
$$
 0.032     293  99.36    39.1    31.1  0.53  0.77      19    24.6    35.0  0.74  1.36
 0.093     548 100.00    35.1    26.5  0.52  0.61      35    32.9    26.5  0.58  0.64
 0.154     675 100.00    28.2    25.1  0.49  0.62      35    23.7    23.8  0.60  0.74
 0.215     853 100.00    23.6    19.6  0.52  0.62      39    25.4    20.0  0.50  0.58
 0.276     920 100.00    18.0    14.2  0.52  0.56      48    16.2    13.1  0.49  0.56
 0.338    1031 100.00    14.7    11.4  0.51  0.54      70    13.6    11.0  0.50  0.51
 0.399    1106 100.00    13.4    10.2  0.53  0.54      68    13.1    10.7  0.44  0.46
 0.460    1193 100.00    12.3    10.0  0.50  0.51      68    10.4     9.2  0.42  0.44
 0.521    1279  99.85    10.5     8.7  0.51  0.52      72    10.8     9.7  0.47  0.50
 0.582    1356  99.72    10.0     8.4  0.51  0.50      75    11.8     8.3  0.52  0.50
 0.643    1364  99.18     9.8     7.5  0.53  0.52      82     9.2     7.5  0.53  0.50
 0.704    1473  98.72     9.1     6.8  0.53  0.52      70     9.7     6.5  0.55  0.53
 0.765    1546  97.89     8.8     6.5  0.55  0.55      79     8.0     6.2  0.53  0.51
 0.826    1484  92.33     7.9     6.2  0.53  0.52      82     8.0     5.7  0.53  0.52
 0.887    1434  87.55     7.5     5.7  0.51  0.49      85     7.6     5.3  0.52  0.50
 0.948    1468  82.59     6.5     4.9  0.52  0.50      50     5.7     4.9  0.60  0.56
 1.010    1351  75.18     5.4     4.2  0.56  0.54      73     4.7     4.4  0.65  0.60
 1.071    1200  67.16     4.4     3.7  0.56  0.55      70     4.2     3.4  0.53  0.51
 1.132    1143  58.99     3.9     3.1  0.55  0.55      51     3.5     3.6  0.61  0.57
 1.193     750  39.07     3.8     2.7  0.53  0.53      42     3.9     2.9  0.55  0.58
$$

 $TABLE: Cycle   31. Fom(<cos(DelPhi)>-acentric, centric, overall v resln:
 $GRAPHS:Cycle   31. M(Fom) v. resln :N:1,3,5,7,8:
 $$
 <4SSQ/LL> NREFa  FOMa  NREFc FOMc NREFall FOMall  SigmaA_Fc1 $$
 $$
  0.0321   293   0.581     0   0.000   293   0.581  0.654
  0.0932   548   0.596     0   0.000   548   0.596  0.672
  0.1542   675   0.611     0   0.000   675   0.611  0.685
  0.2153   853   0.540     0   0.000   853   0.540  0.696
  0.2764   920   0.456     0   0.000   920   0.456  0.705
  0.3375  1031   0.421     0   0.000  1031   0.421  0.718
  0.3986  1106   0.471     0   0.000  1106   0.471  0.751
  0.4597  1193   0.531     0   0.000  1193   0.531  0.740
  0.5208  1279   0.344     0   0.000  1279   0.344  0.531
  0.5819  1356   0.222     0   0.000  1356   0.222  0.364
  0.6430  1364   0.165     0   0.000  1364   0.165  0.304
  0.7041  1473   0.261     0   0.000  1473   0.261  0.470
  0.7652  1546   0.370     0   0.000  1546   0.370  0.602
  0.8262  1484   0.269     0   0.000  1484   0.269  0.463
  0.8873  1434   0.235     0   0.000  1434   0.235  0.409
  0.9484  1468   0.282     0   0.000  1468   0.282  0.496
  1.0095  1351   0.353     0   0.000  1351   0.353  0.588
  1.0706  1200   0.308     0   0.000  1200   0.308  0.501
  1.1317  1143   0.225     0   0.000  1143   0.225  0.387
  1.1928   750   0.136     0   0.000   750   0.136  0.246
 $$
Resolution limits                    =     25.690     0.904
Number of used reflections           =      22467
Percentage observed                  =    85.8624
Percentage of free reflections       =     5.1225
Overall R factor                     =     0.5207
Free R factor                        =     0.5289
Overall weighted R factor            =     0.5425
Free weighted R factor               =     0.5425
Overall weighted R2 factor           =     0.6996
Free weighted R2 factor              =     0.6953
Overall correlation coefficient      =     0.6076
Free correlation coefficient         =     0.5684
Cruickshanks DPI for coordinate error=     0.0241
DPI based on free R factor           =     0.0244
Overall figure of merit              =     0.3407
ML based su of positional parameters =     0.0589
ML based su of thermal parameters    =     1.0064
-----------------------------------------------------------------------------

$TABLE: Rfactor analysis, stats vs cycle  :
$GRAPHS:<Rfactor> vs cycle :N:1,2,3:
:FOM vs cycle :N:1,4:
:-LL vs cycle :N:1,5:
:-LLfree vs cycle :N:1,6:
:Geometry vs cycle:N:1,7,8,9,10,11:
$$
    Ncyc    Rfact    Rfree     FOM      -LL     -LLfree  rmsBOND  zBOND rmsANGL  zANGL rmsCHIRAL $$
$$
       0   0.5397   0.5317   0.347     66009.    3533.2   0.0193  0.987   3.189  1.772   0.092
       1   0.5380   0.5313   0.334     66023.    3532.7   0.0108  0.528   2.391  1.304   0.081
       2   0.5363   0.5315   0.331     66014.    3532.9   0.0088  0.422   2.037  1.111   0.056
       3   0.5352   0.5321   0.329     65921.    3528.3   0.0075  0.359   1.844  1.008   0.036
       4   0.5344   0.5327   0.330     65815.    3523.4   0.0064  0.311   1.713  0.940   0.023
       5   0.5338   0.5330   0.329     65768.    3521.5   0.0057  0.274   1.614  0.887   0.018
       6   0.5334   0.5333   0.329     65708.    3518.9   0.0051  0.245   1.532  0.843   0.019
       7   0.5330   0.5336   0.328     65709.    3519.7   0.0046  0.223   1.462  0.805   0.021
       8   0.5327   0.5339   0.327     65762.    3523.2   0.0042  0.206   1.400  0.771   0.024
       9   0.5324   0.5343   0.327     65720.    3521.4   0.0040  0.192   1.345  0.741   0.026
      10   0.5322   0.5344   0.326     65744.    3523.5   0.0037  0.182   1.296  0.713   0.028
      11   0.5319   0.5345   0.325     65745.    3524.1   0.0036  0.173   1.250  0.688   0.029
      12   0.5315   0.5345   0.324     65724.    3523.4   0.0034  0.166   1.206  0.662   0.029
      13   0.5311   0.5345   0.324     65753.    3525.6   0.0033  0.159   1.164  0.639   0.029
      14   0.5307   0.5346   0.324     65784.    3527.6   0.0031  0.154   1.126  0.617   0.030
      15   0.5302   0.5342   0.323     65865.    3531.8   0.0031  0.151   1.091  0.597   0.030
      16   0.5297   0.5338   0.322     65905.    3534.0   0.0030  0.150   1.059  0.579   0.030
      17   0.5291   0.5331   0.321     65958.    3536.7   0.0030  0.150   1.028  0.562   0.029
      18   0.5283   0.5326   0.322     65955.    3536.5   0.0029  0.149   1.000  0.545   0.029
      19   0.5274   0.5321   0.323     65901.    3532.7   0.0029  0.149   0.972  0.529   0.029
      20   0.5265   0.5316   0.323     65870.    3530.9   0.0029  0.150   0.946  0.515   0.029
      21   0.5258   0.5308   0.323     65814.    3527.7   0.0029  0.151   0.921  0.500   0.028
      22   0.5251   0.5301   0.323     65800.    3525.9   0.0029  0.152   0.897  0.487   0.028
      23   0.5245   0.5295   0.326     65799.    3525.3   0.0029  0.153   0.874  0.474   0.028
      24   0.5239   0.5291   0.329     65806.    3525.1   0.0029  0.154   0.851  0.462   0.027
      25   0.5234   0.5287   0.332     65841.    3527.3   0.0029  0.155   0.829  0.450   0.027
      26   0.5228   0.5287   0.335     65771.    3522.6   0.0029  0.156   0.809  0.438   0.026
      27   0.5222   0.5286   0.339     65628.    3514.3   0.0029  0.156   0.789  0.427   0.026
      28   0.5217   0.5286   0.340     65520.    3508.0   0.0029  0.156   0.769  0.417   0.025
      29   0.5211   0.5288   0.340     65506.    3506.9   0.0029  0.156   0.751  0.407   0.025
      30   0.5207   0.5289   0.341     65565.    3509.9   0.0028  0.155   0.733  0.397   0.024
 $$
 $TEXT:Result: $$ Final results $$
                      Initial    Final
           R factor    0.5397   0.5207
             R free    0.5317   0.5289
     Rms BondLength    0.0193   0.0028
      Rms BondAngle    3.1891   0.7330
     Rms ChirVolume    0.0916   0.0240
 $$
"""


# Provenance: Purely synthetic single-cycle (NCYC 0) log fixture testing the
# Cycle 1 / Ncyc 0 correspondence where detailed resolution table Cycle 1
# corresponds to cycle-summary row Ncyc 0.
SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG = """\
 ### CCP4 9.0: Refmac_5.8.0430     version 5.8.0430 : 01/01/24##
  Data line--- NCYC 0
  Refinement cycles       :     0

$TABLE: Cycle    1. Rfactor analysis, F distribution v resln  :
$GRAPHS:Cycle    1. <Rfactor> v. resln :N:1,6,7,11,12:
$$
M(4SSQ/LL) NR_used %_obs M(Fo_used) M(Fc_used) Rf_used WR_used
NR_free M(Fo_free) M(Fc_free) Rf_free   WR_free $$
$$
 0.050    3100  99.50    42.0    40.1  0.18  0.21     160    41.2    39.0  0.22  0.25
 0.150    3432  98.10    21.5    20.4  0.20  0.23     184    20.8    19.5  0.24  0.27
$$

 $TABLE: Cycle    1. Fom(<cos(DelPhi)>-acentric, centric, overall v resln:
 $GRAPHS:Cycle    1. M(Fom) v. resln :N:1,3,5,7,8:
 $$
 <4SSQ/LL> NREFa  FOMa  NREFc FOMc NREFall FOMall  SigmaA_Fc1 $$
 $$
  0.0500  3000   0.850   100   0.780  3100   0.848  0.910
  0.1500  3332   0.810   100   0.740  3432   0.808  0.885
 $$
Resolution limits                    =     35.000     1.800
Number of used reflections           =       6532
Percentage observed                  =    98.7500
Percentage of free reflections       =     5.0029
Overall R factor                     =     0.1912
Free R factor                        =     0.2315
Overall weighted R factor            =     0.2210
Free weighted R factor               =     0.2610
Overall weighted R2 factor           =     0.2890
Free weighted R2 factor              =     0.3310
Overall figure of merit              =     0.8270
-----------------------------------------------------------------------------

$TABLE: Rfactor analysis, stats vs cycle  :
$GRAPHS:<Rfactor> vs cycle :N:1,2,3:
$$
    Ncyc    Rfact    Rfree     FOM      -LL     -LLfree  rmsBOND  zBOND rmsANGL  zANGL rmsCHIRAL $$
$$
       0   0.1912   0.2315   0.827     12345.     654.3   0.0081  0.410   1.120  0.550   0.045
 $$
 $TEXT:Result: $$ Final results $$
                      Initial    Final
           R factor    0.1912   0.1912
             R free    0.2315   0.2315
     Rms BondLength    0.0081   0.0081
      Rms BondAngle    1.1200   1.1200
     Rms ChirVolume    0.0450   0.0450
 $$
"""


class TestOnesarRefmacLogParser(unittest.TestCase):
    """Hermetic unit tests for parse_refmac_log."""

    def test_historical_ample_excerpt_reconciles_all_cycles_and_bins(self) -> None:
        parsed = parse_refmac_log(HISTORICAL_AMPLE_EXCERPT_LOG)
        # Ensure output is completely JSON-serializable
        roundtrip = json.loads(json.dumps(parsed))
        self.assertEqual(roundtrip["reconciled_final_cycle"], parsed["reconciled_final_cycle"])

        self.assertEqual(
            parsed["source_metadata"]["reported_refmac_version"], "5.8.0049"
        )
        self.assertEqual(parsed["source_metadata"]["reported_suite"], "CCP4 6.4")
        self.assertEqual(parsed["source_metadata"]["requested_ncyc"], 30)

        self.assertEqual(
            [b["id"] for b in parsed["table_blocks"]],
            [
                "initial_resolution_rfactor",
                "initial_resolution_fom",
                "final_resolution_rfactor",
                "final_resolution_fom",
                "cycle_summary",
            ],
        )

        # Verify summary and detailed cycles
        self.assertEqual(parsed["cycle_summary"]["row_count"], 31)
        self.assertEqual(parsed["cycle_summary"]["summary_cycle_min"], 0)
        self.assertEqual(parsed["cycle_summary"]["summary_cycle_max"], 30)
        self.assertEqual(len(parsed["detailed_cycles"]), 31)
        self.assertTrue(
            parsed["cycle_r_values"]["all_ordered_detail_pairs_equal_summary_values"]
        )
        self.assertTrue(
            parsed["consistency_checks"][
                "initial_detail_summary_and_final_results_initial_values_equal"
            ]
        )
        self.assertTrue(
            parsed["consistency_checks"][
                "final_detail_summary_and_final_results_final_values_equal"
            ]
        )
        self.assertEqual(
            parsed["cycle_r_values"]["detail_rfactor_table_cycle_labels"], [1, 31]
        )

        # Initial and final R pairs and precision
        init_cyc = parsed["reconciled_initial_cycle"]
        self.assertEqual(init_cyc["summary_ncyc"], 0)
        self.assertEqual(init_cyc["detailed_cycle"], 1)
        self.assertEqual(init_cyc["r_work_token"], "0.5397")
        self.assertEqual(init_cyc["r_free_token"], "0.5317")
        self.assertEqual(init_cyc["r_work_decimal_places"], 4)
        self.assertEqual(init_cyc["r_free_decimal_places"], 4)

        final_cyc = parsed["reconciled_final_cycle"]
        self.assertEqual(final_cyc["summary_ncyc"], 30)
        self.assertEqual(final_cyc["detailed_cycle"], 31)
        self.assertEqual(final_cyc["resolution_table_cycle"], 31)
        self.assertEqual(final_cyc["r_work_token"], "0.5207")
        self.assertEqual(final_cyc["r_free_token"], "0.5289")
        self.assertAlmostEqual(final_cyc["r_work"], 0.5207)
        self.assertAlmostEqual(final_cyc["r_free"], 0.5289)
        self.assertEqual(final_cyc["r_work_decimal_places"], 4)
        self.assertEqual(final_cyc["r_free_decimal_places"], 4)
        self.assertEqual(final_cyc["nr_used_sum"], 22467)
        self.assertEqual(final_cyc["nr_free_sum"], 1213)
        self.assertEqual(final_cyc["combined_reported_count"], 23680)

        # Verify unweighted R is distinct from weighted R, R2, and FOM
        final_detail = parsed["detailed_cycles"][-1]
        self.assertEqual(final_detail["overall_r_token"], "0.5207")
        self.assertEqual(final_detail["free_r_token"], "0.5289")
        self.assertEqual(final_detail["overall_weighted_r_token"], "0.5425")
        self.assertEqual(final_detail["free_weighted_r_token"], "0.5425")
        self.assertEqual(final_detail["overall_weighted_r2_token"], "0.6996")
        self.assertEqual(final_detail["free_weighted_r2_token"], "0.6953")
        self.assertEqual(final_detail["overall_fom_token"], "0.3407")

        # Verify per-bin counts and 2-decimal-place R tokens
        final_bins = parsed["final_resolution_bins"]
        self.assertEqual(final_bins["bin_count"], 20)
        self.assertEqual(final_bins["nr_used_sum"], 22467)
        self.assertEqual(final_bins["nr_free_sum"], 1213)
        self.assertEqual(final_bins["rf_used_printed_decimal_places"], 2)
        self.assertEqual(final_bins["rf_free_printed_decimal_places"], 2)
        self.assertEqual(final_bins["bins"][0]["nr_used"], 293)
        self.assertEqual(final_bins["bins"][0]["nr_free"], 19)
        self.assertEqual(final_bins["bins"][0]["rf_used_token"], "0.53")
        self.assertEqual(final_bins["bins"][0]["rf_free_token"], "0.74")
        self.assertEqual(final_bins["bins"][0]["wr_free_token"], "1.36")
        self.assertEqual(final_bins["bins"][-1]["nr_used"], 750)
        self.assertEqual(final_bins["bins"][-1]["nr_free"], 42)
        self.assertEqual(final_bins["bins"][-1]["rf_used_token"], "0.53")
        self.assertEqual(final_bins["bins"][-1]["rf_free_token"], "0.55")

    def test_single_cycle_cycle1_ncyc0_correspondence(self) -> None:
        parsed = parse_refmac_log(SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG)
        self.assertEqual(parsed["cycle_summary"]["row_count"], 1)
        self.assertEqual(parsed["cycle_summary"]["summary_cycle_min"], 0)
        self.assertEqual(parsed["cycle_summary"]["summary_cycle_max"], 0)
        self.assertEqual(len(parsed["detailed_cycles"]), 1)
        self.assertEqual(parsed["detailed_cycles"][0]["detailed_cycle"], 1)
        self.assertEqual(parsed["detailed_cycles"][0]["summary_ncyc"], 0)

        final_cyc = parsed["reconciled_final_cycle"]
        self.assertEqual(final_cyc["summary_ncyc"], 0)
        self.assertEqual(final_cyc["detailed_cycle"], 1)
        self.assertEqual(final_cyc["resolution_table_cycle"], 1)
        self.assertEqual(final_cyc["r_work_token"], "0.1912")
        self.assertEqual(final_cyc["r_free_token"], "0.2315")
        self.assertEqual(final_cyc["nr_used_sum"], 6532)
        self.assertEqual(final_cyc["nr_free_sum"], 344)
        self.assertEqual(final_cyc["combined_reported_count"], 6876)

    def test_unweighted_r_above_one_accepted_and_precision_preserved(self) -> None:
        log_text = (
            SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace("0.1912", "1.12500")
            .replace("0.2315", "1.34000")
            .replace("0.18  0.21", "1.080 1.210")
            .replace("0.22  0.25", "1.420 1.550")
            .replace("0.20  0.23", "1.150 1.280")
            .replace("0.24  0.27", "1.260 1.390")
        )
        parsed = parse_refmac_log(log_text)
        final_cyc = parsed["reconciled_final_cycle"]
        self.assertEqual(final_cyc["r_work_token"], "1.12500")
        self.assertEqual(final_cyc["r_free_token"], "1.34000")
        self.assertAlmostEqual(final_cyc["r_work"], 1.125)
        self.assertAlmostEqual(final_cyc["r_free"], 1.34)
        self.assertEqual(final_cyc["r_work_decimal_places"], 5)
        self.assertEqual(final_cyc["r_free_decimal_places"], 5)
        self.assertEqual(
            parsed["final_resolution_bins"]["rf_used_printed_decimal_places"], 3
        )
        self.assertEqual(
            parsed["final_resolution_bins"]["rf_free_printed_decimal_places"], 3
        )

    def test_competing_unrelated_tables_ignored_for_rfactor_extraction(self) -> None:
        competing_before = """\
$TABLE: Cycle   99. Anisotropic scaling v resln :
$GRAPHS:Cycle   99. Scale v. resln :N:1,2,3:
$$
M(4SSQ/LL) Scale_k   B_aniso $$
$$
 0.050      0.9999    0.8888
 0.150      0.7777    0.6666
$$
"""
        competing_after = """\
$TABLE: Restraint geometry stats vs cycle :
$GRAPHS:Restraint rms vs cycle :N:1,2,3:
$$
Ncyc rmsBOND rmsANGL $$
$$
   0  0.9111  0.9222
$$
"""
        augmented = (
            competing_before
            + SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG
            + competing_after
        )
        parsed = parse_refmac_log(augmented)
        self.assertEqual(
            [b["table_kind"] for b in parsed["table_blocks"]],
            ["other", "resolution_rfactor", "resolution_fom", "cycle_summary", "other"],
        )
        self.assertEqual(parsed["reconciled_final_cycle"]["r_work_token"], "0.1912")
        self.assertEqual(parsed["reconciled_final_cycle"]["r_free_token"], "0.2315")
        self.assertEqual(parsed["reconciled_final_cycle"]["nr_used_sum"], 6532)
        self.assertEqual(parsed["reconciled_final_cycle"]["nr_free_sum"], 344)

        # Log with only competing tables and no Rfactor table must fail
        with self.assertRaisesRegex(ValueError, "Missing required"):
            parse_refmac_log(competing_before + competing_after)

    def test_standalone_header_end_double_dollar_accepted(self) -> None:
        log_text = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "NR_free M(Fo_free) M(Fc_free) Rf_free   WR_free $$\n$$",
            "NR_free M(Fo_free) M(Fc_free) Rf_free   WR_free\n$$\n$$",
        )
        parsed = parse_refmac_log(log_text)
        roles = parsed["final_resolution_bins"]["double_dollar_roles"]
        self.assertEqual(roles["data_start_line"], roles["header_end_line"] + 1)
        self.assertEqual(parsed["final_resolution_bins"]["nr_used_sum"], 6532)

    def test_malformed_delimiters_rejected(self) -> None:
        # 1. Missing data_start $$ (only 3 $$ in resolution table)
        missing_third_dd = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "NR_free M(Fo_free) M(Fc_free) Rf_free   WR_free $$\n$$",
            "NR_free M(Fo_free) M(Fc_free) Rf_free   WR_free $$",
        )
        with self.assertRaisesRegex(ValueError, "data_start \\$\\$"):
            parse_refmac_log(missing_third_dd)

        # 2. Missing closing data_end $$ on cycle_summary table (reaches next $TEXT title with $$)
        missing_fourth_dd = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "       0   0.1912   0.2315   0.827     12345.     654.3   0.0081  0.410   1.120  0.550   0.045\n $$",
            "       0   0.1912   0.2315   0.827     12345.     654.3   0.0081  0.410   1.120  0.550   0.045",
        )
        with self.assertRaisesRegex(
            ValueError, r"Multiple \$\$ delimiters on line .* in \$TABLE"
        ):
            parse_refmac_log(missing_fourth_dd)

        # 2b. Missing closing data_end $$ before a non-$$ boundary (reaches next $TABLE)
        missing_resln_fourth_dd = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            " 0.150    3432  98.10    21.5    20.4  0.20  0.23     184    20.8    19.5  0.24  0.27\n$$\n\n $TABLE:",
            " 0.150    3432  98.10    21.5    20.4  0.20  0.23     184    20.8    19.5  0.24  0.27\n $TABLE:",
        )
        with self.assertRaisesRegex(ValueError, r"Unclosed data block in \$TABLE"):
            parse_refmac_log(missing_resln_fourth_dd)

        # 3. Multiple $$ on a single line inside $TABLE
        double_dd_line = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "$$\nM(4SSQ/LL)",
            "$$ $$\nM(4SSQ/LL)",
        )
        with self.assertRaisesRegex(ValueError, "Multiple \\$\\$ delimiters"):
            parse_refmac_log(double_dd_line)

        # 4. Trailing tokens after header_end $$
        trailing_after_header_dd = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "Rf_free   WR_free $$",
            "Rf_free   WR_free $$ EXTRA_COL",
        )
        with self.assertRaisesRegex(ValueError, "Trailing tokens after header_end \\$\\$"):
            parse_refmac_log(trailing_after_header_dd)

        # 5. Unclosed $TEXT:Result: block
        unclosed_result = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.rstrip()
        assert unclosed_result.endswith("$$")
        unclosed_result = unclosed_result[:-2]
        with self.assertRaisesRegex(ValueError, "Unclosed \\$TEXT:Result:"):
            parse_refmac_log(unclosed_result)

        # 6. Stray $$ outside any $TABLE or $TEXT block
        stray_dd = "$$\n" + SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG
        with self.assertRaisesRegex(ValueError, "Stray or malformed loggraph delimiter"):
            parse_refmac_log(stray_dd)

    def test_conflicting_r_pairs_rejected(self) -> None:
        # 1. Final detailed Overall R factor conflicts with cycle_summary Rfact
        conflict_detail_work = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
            "Overall R factor                     =     0.5207",
            "Overall R factor                     =     0.5208",
        )
        with self.assertRaisesRegex(ValueError, "Conflicting R-work"):
            parse_refmac_log(conflict_detail_work)

        # 2. Final detailed Free R factor conflicts with cycle_summary Rfree
        conflict_detail_free = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
            "Free R factor                        =     0.5289",
            "Free R factor                        =     0.5290",
        )
        with self.assertRaisesRegex(ValueError, "Conflicting R-free"):
            parse_refmac_log(conflict_detail_free)

        # 3. Final results R factor Final conflicts with cycle_summary
        conflict_final_res_work = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
            "           R factor    0.5397   0.5207",
            "           R factor    0.5397   0.5210",
        )
        with self.assertRaisesRegex(ValueError, "Conflicting R-work"):
            parse_refmac_log(conflict_final_res_work)

        # 4. Final results R free Final conflicts with cycle_summary
        conflict_final_res_free = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
            "             R free    0.5317   0.5289",
            "             R free    0.5317   0.5299",
        )
        with self.assertRaisesRegex(ValueError, "Conflicting R-free"):
            parse_refmac_log(conflict_final_res_free)

        # 5. Final results Initial R factor conflicts with initial cycle (Ncyc 0)
        conflict_init_res_work = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
            "           R factor    0.5397   0.5207",
            "           R factor    0.5399   0.5207",
        )
        with self.assertRaisesRegex(ValueError, "Conflicting R-work"):
            parse_refmac_log(conflict_init_res_work)

        # 6. Intermediate cycle (Ncyc 15) mismatch between detail and summary
        conflict_mid_cycle = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
            "      15   0.5302   0.5342",
            "      15   0.5309   0.5342",
        )
        with self.assertRaisesRegex(ValueError, "Conflicting R-work"):
            parse_refmac_log(conflict_mid_cycle)

        # 7. Unequal Decimal value at 5th decimal place (0.19121 vs 0.1912) rejected with no tolerance
        conflict_fifth_dp = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "Overall R factor                     =     0.1912",
            "Overall R factor                     =     0.19121",
        )
        with self.assertRaisesRegex(ValueError, "Conflicting R-work"):
            parse_refmac_log(conflict_fifth_dp)

        # 8. Missing unweighted Overall R factor (only weighted R present)
        missing_unweighted = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "Overall R factor                     =     0.1912\n",
            "",
        )
        with self.assertRaisesRegex(
            ValueError, "missing paired unweighted 'Overall R factor' / 'Free R factor'"
        ):
            parse_refmac_log(missing_unweighted)

    def test_decimal_r_reconciliation_with_trailing_zeros_preserves_tokens(self) -> None:
        # Equal Decimal values with different trailing zeros (0.19120 vs 0.1912 vs 0.191200) pass
        trailing_zero_log = (
            SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
                "Overall R factor                     =     0.1912",
                "Overall R factor                     =     0.19120",
            )
            .replace(
                "Free R factor                        =     0.2315",
                "Free R factor                        =     0.231500",
            )
            .replace(
                "           R factor    0.1912   0.1912",
                "           R factor    0.191200 0.1912000",
            )
            .replace(
                "             R free    0.2315   0.2315",
                "             R free    0.23150  0.2315",
            )
        )
        parsed = parse_refmac_log(trailing_zero_log)
        self.assertTrue(
            parsed["cycle_r_values"]["all_ordered_detail_pairs_equal_summary_values"]
        )
        self.assertTrue(
            parsed["consistency_checks"][
                "initial_detail_summary_and_final_results_initial_values_equal"
            ]
        )
        self.assertTrue(
            parsed["consistency_checks"][
                "final_detail_summary_and_final_results_final_values_equal"
            ]
        )

        init_cyc = parsed["reconciled_initial_cycle"]
        self.assertEqual(init_cyc["detailed_r_work_token"], "0.19120")
        self.assertEqual(init_cyc["detailed_r_work_decimal_places"], 5)
        self.assertEqual(init_cyc["summary_r_work_token"], "0.1912")
        self.assertEqual(init_cyc["summary_r_work_decimal_places"], 4)
        self.assertEqual(init_cyc["final_results_r_work_token"], "0.191200")
        self.assertEqual(init_cyc["final_results_r_work_decimal_places"], 6)

        final_cyc = parsed["reconciled_final_cycle"]
        self.assertEqual(final_cyc["detailed_r_free_token"], "0.231500")
        self.assertEqual(final_cyc["detailed_r_free_decimal_places"], 6)
        self.assertEqual(final_cyc["summary_r_free_token"], "0.2315")
        self.assertEqual(final_cyc["summary_r_free_decimal_places"], 4)
        self.assertEqual(final_cyc["final_results_r_work_token"], "0.1912000")
        self.assertEqual(final_cyc["final_results_r_work_decimal_places"], 7)

    def test_truncated_rows_and_malformed_headers_rejected(self) -> None:
        # 1. Truncated row in resolution R-factor table (11 tokens instead of 12)
        truncated_bin_row = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            " 0.150    3432  98.10    21.5    20.4  0.20  0.23     184    20.8    19.5  0.24  0.27",
            " 0.150    3432  98.10    21.5    20.4  0.20  0.23     184    20.8    19.5  0.24",
        )
        with self.assertRaisesRegex(ValueError, "Row width mismatch"):
            parse_refmac_log(truncated_bin_row)

        # 2. Truncated row in cycle-summary table (10 tokens instead of 11)
        truncated_summary_row = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "       0   0.1912   0.2315   0.827     12345.     654.3   0.0081  0.410   1.120  0.550   0.045",
            "       0   0.1912   0.2315   0.827     12345.     654.3   0.0081  0.410   1.120  0.550",
        )
        with self.assertRaisesRegex(ValueError, "Row width mismatch"):
            parse_refmac_log(truncated_summary_row)

        # 3. Truncated row in Final results block (missing Final value for known label 'R free')
        truncated_final_results = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "             R free    0.2315   0.2315",
            "             R free    0.2315",
        )
        with self.assertRaisesRegex(
            ValueError,
            r"Expected exactly 2 values \(Initial, Final\) for 'R free' in Final results block",
        ):
            parse_refmac_log(truncated_final_results)

        # 4. Swapped/corrupted header in resolution R-factor table
        corrupted_header = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "Rf_used WR_used",
            "WR_used Rf_used",
        )
        with self.assertRaisesRegex(
            ValueError, "Unexpected resolution R-factor table header"
        ):
            parse_refmac_log(corrupted_header)

    def test_final_results_known_and_other_label_cardinality_and_duplicates(self) -> None:
        # Extra value on known 'R factor' row rejected
        extra_rfactor_val = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "           R factor    0.1912   0.1912",
            "           R factor    0.1912   0.1912   0.1912",
        )
        with self.assertRaisesRegex(
            ValueError,
            r"Expected exactly 2 values \(Initial, Final\) for 'R factor' in Final results block",
        ):
            parse_refmac_log(extra_rfactor_val)

        # Extra value on known 'R free' row rejected
        extra_rfree_val = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "             R free    0.2315   0.2315",
            "             R free    0.2315   0.2315   0.2500",
        )
        with self.assertRaisesRegex(
            ValueError,
            r"Expected exactly 2 values \(Initial, Final\) for 'R free' in Final results block",
        ):
            parse_refmac_log(extra_rfree_val)

        # Duplicate 'R factor' row rejected
        dup_rfactor = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "           R factor    0.1912   0.1912",
            "           R factor    0.1912   0.1912\n           R factor    0.1912   0.1912",
        )
        with self.assertRaisesRegex(
            ValueError, "Duplicate 'R factor' row in Final results block"
        ):
            parse_refmac_log(dup_rfactor)

        # Duplicate 'R free' row rejected
        dup_rfree = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "             R free    0.2315   0.2315",
            "             R free    0.2315   0.2315\n             R free    0.2315   0.2315",
        )
        with self.assertRaisesRegex(
            ValueError, "Duplicate 'R free' row in Final results block"
        ):
            parse_refmac_log(dup_rfree)

        # Legitimate other two-value label in Final results accepted
        other_label_ok = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "     Rms ChirVolume    0.0450   0.0450",
            "     Rms ChirVolume    0.0450   0.0450\n      Rms Planarity    0.0120   0.0080",
        )
        parsed_other = parse_refmac_log(other_label_ok)
        self.assertEqual(parsed_other["final_results_block"]["rows"][-1]["label"], "Rms Planarity")

        # Extra value on other label rejected
        other_label_extra = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "     Rms ChirVolume    0.0450   0.0450",
            "     Rms ChirVolume    0.0450   0.0450\n      Rms Planarity    0.0120   0.0080   0.0040",
        )
        with self.assertRaisesRegex(
            ValueError,
            r"Expected exactly 2 values \(Initial, Final\) for 'Rms Planarity' in Final results block",
        ):
            parse_refmac_log(other_label_extra)

    def test_nan_infinity_negative_and_malformed_r_values_rejected_while_large_finite_accepted(
        self,
    ) -> None:
        # Large finite ordinary and weighted R values (such as 99.99 or 100.0000) are accepted
        large_finite_log = (
            SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace("0.1912", "100.0000")
            .replace("0.2315", "99.9900")
            .replace("0.18  0.21", "99.99 100.00")
            .replace("0.22  0.25", "100.00 120.50")
            .replace("0.2210", "100.0000")
            .replace("0.2610", "105.5000")
        )
        parsed_large = parse_refmac_log(large_finite_log)
        self.assertEqual(
            parsed_large["reconciled_final_cycle"]["r_work_token"], "100.0000"
        )
        self.assertEqual(
            parsed_large["reconciled_final_cycle"]["r_free_token"], "99.9900"
        )
        self.assertAlmostEqual(
            parsed_large["reconciled_final_cycle"]["r_work"], 100.0
        )

        # Non-finite, negative, overflow ('*'), and malformed R tokens are rejected
        for bad_token in (
            "NaN",
            "nan",
            "Inf",
            "-inf",
            "****",
            "-0.1912",
            "N/A",
            ".1912",
            "0.",
        ):
            with self.subTest(bad_bin_r=bad_token):
                bad_bin_log = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
                    "0.20  0.23",
                    f"{bad_token}  0.23",
                )
                with self.assertRaisesRegex(ValueError, "R token"):
                    parse_refmac_log(bad_bin_log)

            with self.subTest(bad_detail_r=bad_token):
                bad_detail_log = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
                    "Overall R factor                     =     0.1912",
                    f"Overall R factor                     =     {bad_token}",
                )
                with self.assertRaisesRegex(ValueError, "R token"):
                    parse_refmac_log(bad_detail_log)

            with self.subTest(bad_summary_r=bad_token):
                bad_summary_log = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
                    "       0   0.1912   0.2315",
                    f"       0   {bad_token}   0.2315",
                )
                with self.assertRaisesRegex(ValueError, "R token"):
                    parse_refmac_log(bad_summary_log)

    def test_intermediate_resolution_rfactor_table_validated_and_retained(self) -> None:
        intermediate_table = (
            "$TABLE: Cycle    2. Rfactor analysis, F distribution v resln  :\n"
            "$GRAPHS:Cycle    2. <Rfactor> v. resln :N:1,6,7,11,12:\n"
            "$$\n"
            "M(4SSQ/LL) NR_used %_obs M(Fo_used) M(Fc_used) Rf_used WR_used\n"
            "NR_free M(Fo_free) M(Fc_free) Rf_free   WR_free $$\n"
            "$$\n"
            " 0.032   11000  99.36    39.1    31.2  0.53  0.76     600    24.6    36.2  0.75  1.45\n"
            " 0.093   11467 100.00    35.1    25.7  0.52  0.60     613    32.9    26.5  0.52  0.58\n"
            "$$\n"
            "Number of used reflections           =      22467\n"
        )
        anchor = (
            "Overall R factor                     =     0.5380\n"
            "Free R factor                        =     0.5313\n"
        )
        with_intermediate = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
            anchor, intermediate_table + anchor, 1
        )
        parsed = parse_refmac_log(with_intermediate)
        tables = parsed["resolution_bin_values"]["tables"]
        self.assertEqual(len(tables), 3)
        self.assertEqual(
            [t["phase"] for t in tables], ["initial", "intermediate", "final"]
        )
        self.assertEqual([t["detailed_cycle"] for t in tables], [1, 2, 31])
        self.assertEqual(tables[1]["summary_ncyc"], 1)
        self.assertEqual(tables[1]["nr_used_sum"], 22467)
        self.assertEqual(tables[1]["nr_free_sum"], 1213)
        self.assertEqual(parsed["initial_resolution_bins"]["detailed_cycle"], 1)
        self.assertEqual(parsed["final_resolution_bins"]["detailed_cycle"], 31)

        # 1. NaN R token inside intermediate resolution table rejected
        bad_intermediate_r = with_intermediate.replace(
            "0.53  0.76     600", "NaN   0.76     600", 1
        )
        with self.assertRaisesRegex(ValueError, "R token"):
            parse_refmac_log(bad_intermediate_r)

        # 2. Negative and fractional count inside intermediate resolution table rejected
        neg_intermediate_count = with_intermediate.replace(
            " 0.032   11000", " 0.032  -11000", 1
        )
        with self.assertRaisesRegex(ValueError, "NR_used"):
            parse_refmac_log(neg_intermediate_count)

        frac_intermediate_count = with_intermediate.replace(
            " 0.032   11000", " 0.032 11000.5", 1
        )
        with self.assertRaisesRegex(ValueError, "NR_used"):
            parse_refmac_log(frac_intermediate_count)

        # 3. Same-cycle detailed Number of used reflections mismatch against intermediate table sum rejected
        mismatch_intermediate_used = with_intermediate.replace(
            "Number of used reflections           =      22467\nOverall R factor                     =     0.5380",
            "Number of used reflections           =      22468\nOverall R factor                     =     0.5380",
            1,
        )
        with self.assertRaisesRegex(
            ValueError,
            "Detailed Cycle 2 Number of used reflections .* != Cycle 2 resolution table NR_used sum",
        ):
            parse_refmac_log(mismatch_intermediate_used)

    def test_cgmat_cycle_markers_validated_and_retained(self) -> None:
        # Optional absence in HISTORICAL_AMPLE_EXCERPT_LOG
        parsed_no_markers = parse_refmac_log(HISTORICAL_AMPLE_EXCERPT_LOG)
        self.assertEqual(parsed_no_markers["cgmat_cycle_markers"], [])
        self.assertIsNone(parsed_no_markers["detailed_cycles"][0]["cgmat_cycle_number"])

        # Native pattern: CGMAT cycle number 1..30 before detailed cycles 1..30, no marker 31 before detailed 31
        lines = HISTORICAL_AMPLE_EXCERPT_LOG.splitlines()
        out_lines: list[str] = []
        overall_r_seen = 0
        for line in lines:
            if line.startswith("Resolution limits") and overall_r_seen == 0:
                out_lines.append("     CGMAT cycle number =      1")
            elif line.startswith("Overall R factor"):
                overall_r_seen += 1
                if 2 <= overall_r_seen <= 30:
                    out_lines.append(
                        f"     CGMAT cycle number =     {overall_r_seen:2d}"
                    )
            out_lines.append(line)
        log_with_30_markers = "\n".join(out_lines) + "\n"
        parsed_markers = parse_refmac_log(log_with_30_markers)
        self.assertEqual(len(parsed_markers["cgmat_cycle_markers"]), 30)
        self.assertEqual(
            [m["cycle_number"] for m in parsed_markers["cgmat_cycle_markers"]],
            list(range(1, 31)),
        )
        self.assertEqual(
            [m["detailed_cycle"] for m in parsed_markers["cgmat_cycle_markers"]],
            list(range(1, 31)),
        )
        self.assertEqual(parsed_markers["detailed_cycles"][0]["cgmat_cycle_number"], 1)
        self.assertEqual(
            parsed_markers["detailed_cycles"][29]["cgmat_cycle_number"], 30
        )
        self.assertIsNone(parsed_markers["detailed_cycles"][30]["cgmat_cycle_number"])

        # Duplicate CGMAT marker rejected
        dup_marker_log = log_with_30_markers.replace(
            "     CGMAT cycle number =      2",
            "     CGMAT cycle number =      1",
            1,
        )
        with self.assertRaisesRegex(ValueError, "CGMAT cycle number"):
            parse_refmac_log(dup_marker_log)

        # Out-of-order / misassociated CGMAT marker rejected
        misassociated_marker = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "Resolution limits",
            "     CGMAT cycle number =      2\nResolution limits",
        )
        with self.assertRaisesRegex(
            ValueError, "CGMAT cycle number 2 .* does not match associated detailed Cycle 1"
        ):
            parse_refmac_log(misassociated_marker)

        # Non-positive / non-finite CGMAT marker rejected
        for bad_cgmat in ("0", "-1", "1.5", "NaN", "1 2"):
            with self.subTest(bad_cgmat=bad_cgmat):
                bad_cgmat_log = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
                    "Resolution limits",
                    f"     CGMAT cycle number =      {bad_cgmat}\nResolution limits",
                )
                with self.assertRaisesRegex(ValueError, "CGMAT cycle number"):
                    parse_refmac_log(bad_cgmat_log)

    def test_optional_correlation_dpi_and_ml_su_fields_validated(self) -> None:
        parsed = parse_refmac_log(HISTORICAL_AMPLE_EXCERPT_LOG)
        init_detail = parsed["detailed_cycles"][0]
        final_detail = parsed["detailed_cycles"][-1]

        # Absent on Cycle 1 in excerpt
        self.assertIsNone(init_detail["overall_correlation_coefficient"])
        self.assertIsNone(init_detail["free_correlation_coefficient"])
        self.assertIsNone(init_detail["cruickshanks_dpi"])
        self.assertIsNone(init_detail["dpi_free_r"])
        self.assertIsNone(init_detail["ml_su_positional"])
        self.assertIsNone(init_detail["ml_su_thermal"])

        # Present on Cycle 31 with tokens, values, and source line numbers
        self.assertEqual(
            final_detail["overall_correlation_coefficient_token"], "0.6076"
        )
        self.assertAlmostEqual(
            final_detail["overall_correlation_coefficient"], 0.6076
        )
        self.assertIsNotNone(final_detail["overall_correlation_coefficient_line"])
        self.assertEqual(final_detail["free_correlation_coefficient_token"], "0.5684")
        self.assertEqual(final_detail["cruickshanks_dpi_token"], "0.0241")
        self.assertEqual(final_detail["dpi_free_r_token"], "0.0244")
        self.assertEqual(final_detail["ml_su_positional_token"], "0.0589")
        self.assertEqual(final_detail["ml_su_thermal_token"], "1.0064")

        # Non-finite or wrong-cardinality optional metric values rejected
        for label, orig_val in (
            ("Overall correlation coefficient", "0.6076"),
            ("Free correlation coefficient", "0.5684"),
            ("Cruickshanks DPI for coordinate error", "0.0241"),
            ("DPI based on free R factor", "0.0244"),
            ("ML based su of positional parameters", "0.0589"),
            ("ML based su of thermal parameters", "1.0064"),
        ):
            for bad_rhs in ("NaN", "Inf", "****", f"{orig_val} {orig_val}", ""):
                with self.subTest(label=label, bad_rhs=bad_rhs):
                    mutated = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
                        orig_val, bad_rhs, 1
                    )
                    with self.assertRaises(ValueError):
                        parse_refmac_log(mutated)

    def test_fom_resolution_tables_cycle_order_and_row_count_identity(self) -> None:
        # FOM population may differ from R-table NR_used / NR_free as long as NREFall == NREFa + NREFc
        different_fom_pop = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "  0.0500  3000   0.850   100   0.780  3100   0.848  0.910",
            "  0.0500   400   0.850    50   0.780   450   0.848  0.910",
        )
        parsed = parse_refmac_log(different_fom_pop)
        self.assertEqual(parsed["reconciled_final_cycle"]["nr_used_sum"], 6532)

        # Within-row NREFall != NREFa + NREFc rejected
        bad_fom_sum = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "  0.0500  3000   0.850   100   0.780  3100   0.848  0.910",
            "  0.0500  3000   0.850   100   0.780  3101   0.848  0.910",
        )
        with self.assertRaisesRegex(
            ValueError, r"FOM table row NREFall \(3101\) != NREFa \(3000\) \+ NREFc \(100\)"
        ):
            parse_refmac_log(bad_fom_sum)

        # Duplicate / non-increasing FOM cycle number rejected
        dup_fom_cycle = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
            " $TABLE: Cycle   31. Fom(<cos(DelPhi)>-acentric, centric, overall v resln:\n"
            " $GRAPHS:Cycle   31. M(Fom) v. resln :N:1,3,5,7,8:",
            " $TABLE: Cycle    1. Fom(<cos(DelPhi)>-acentric, centric, overall v resln:\n"
            " $GRAPHS:Cycle    1. M(Fom) v. resln :N:1,3,5,7,8:",
        )
        with self.assertRaisesRegex(
            ValueError, "Non-increasing or duplicate resolution FOM table Cycle 1"
        ):
            parse_refmac_log(dup_fom_cycle)

        # Misaligned FOM table cycle number rejected
        misaligned_fom_cycle = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
            " $TABLE: Cycle   31. Fom(<cos(DelPhi)>-acentric, centric, overall v resln:\n"
            " $GRAPHS:Cycle   31. M(Fom) v. resln :N:1,3,5,7,8:",
            " $TABLE: Cycle   30. Fom(<cos(DelPhi)>-acentric, centric, overall v resln:\n"
            " $GRAPHS:Cycle   30. M(Fom) v. resln :N:1,3,5,7,8:",
        )
        with self.assertRaisesRegex(
            ValueError, "Resolution FOM table Cycle 30 .* is misaligned"
        ):
            parse_refmac_log(misaligned_fom_cycle)

    def test_percentage_tokens_domain_and_precision(self) -> None:
        # 0 and 100 boundaries accepted; 0.0000 free percentage with positive NR_free accepted
        boundary_pct_log = (
            SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
                "Percentage observed                  =    98.7500",
                "Percentage observed                  =   100.0000",
            )
            .replace(
                "Percentage of free reflections       =     5.0029",
                "Percentage of free reflections       =     0.0000",
            )
            .replace("99.50", "0.00")
            .replace("98.10", "100.00")
        )
        parsed = parse_refmac_log(boundary_pct_log)
        detail = parsed["detailed_cycles"][0]
        self.assertEqual(detail["percentage_observed_token"], "100.0000")
        self.assertAlmostEqual(detail["percentage_observed"], 100.0)
        self.assertEqual(detail["percentage_observed_decimal_places"], 4)
        self.assertEqual(detail["percentage_free_token"], "0.0000")
        self.assertAlmostEqual(detail["percentage_free"], 0.0)
        self.assertEqual(detail["percentage_free_decimal_places"], 4)
        self.assertGreater(parsed["final_resolution_bins"]["nr_free_sum"], 0)

        # Scientific-notation percentages compute effective decimal places after exponent
        exp_pct_log = (
            SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
                "Percentage observed                  =    98.7500",
                "Percentage observed                  =   8.58624e1",
            )
            .replace(
                "Percentage of free reflections       =     5.0029",
                "Percentage of free reflections       =   5.12250e0",
            )
            .replace("99.50", "1e2", 1)
        )
        parsed_exp = parse_refmac_log(exp_pct_log)
        exp_detail = parsed_exp["detailed_cycles"][0]
        self.assertEqual(exp_detail["percentage_observed_token"], "8.58624e1")
        self.assertAlmostEqual(exp_detail["percentage_observed"], 85.8624)
        self.assertEqual(exp_detail["percentage_observed_decimal_places"], 4)
        self.assertEqual(exp_detail["percentage_free_token"], "5.12250e0")
        self.assertAlmostEqual(exp_detail["percentage_free"], 5.1225)
        self.assertEqual(exp_detail["percentage_free_decimal_places"], 5)
        self.assertEqual(
            parsed_exp["final_resolution_bins"]["bins"][0]["pct_obs_token"], "1e2"
        )
        self.assertAlmostEqual(
            parsed_exp["final_resolution_bins"]["bins"][0]["pct_obs"], 100.0
        )
        self.assertEqual(
            parsed_exp["final_resolution_bins"]["bins"][0]["pct_obs_decimal_places"],
            0,
        )

        # Out-of-domain (< 0, > 100) and non-finite percentages rejected
        for bad_pct in ("-0.01", "100.01", "NaN", "Inf", "****"):
            with self.subTest(bad_pct_obs=bad_pct):
                bad_obs = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
                    "Percentage observed                  =    98.7500",
                    f"Percentage observed                  =    {bad_pct}",
                )
                with self.assertRaisesRegex(ValueError, "Percentage observed"):
                    parse_refmac_log(bad_obs)

            with self.subTest(bad_pct_free=bad_pct):
                bad_free = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
                    "Percentage of free reflections       =     5.0029",
                    f"Percentage of free reflections       =     {bad_pct}",
                )
                with self.assertRaisesRegex(
                    ValueError, "Percentage of free reflections"
                ):
                    parse_refmac_log(bad_free)

            with self.subTest(bad_bin_pct=bad_pct):
                bad_bin = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
                    "99.50", bad_pct, 1
                )
                with self.assertRaisesRegex(ValueError, "%_obs"):
                    parse_refmac_log(bad_bin)

    def test_underscore_and_non_native_numeric_literals_rejected(self) -> None:
        # Underscores in percentage, generic float, integer count, and R fields must fail
        for target, replacement, err_re in (
            (
                "Percentage observed                  =    85.8624",
                "Percentage observed                  =   8_5.8624",
                "Malformed numeric token '8_5.8624'",
            ),
            (
                " 0.032     293  99.36",
                " 0.032     293 9_9.36",
                "Malformed numeric token '9_9.36'",
            ),
            (
                "Overall correlation coefficient      =     0.6076",
                "Overall correlation coefficient      =    0_0.6076",
                "Malformed numeric token '0_0.6076'",
            ),
            (
                "Overall weighted R factor            =     0.5425",
                "Overall weighted R factor            =    0_0.5425",
                "Malformed numeric token '0_0.5425'",
            ),
            (
                "      30   0.5207   0.5289   0.341     65565.",
                "      30   0.5207   0.5289   0.341    65_565.",
                "Malformed numeric token '65_565.'",
            ),
            (
                "Number of used reflections           =      22467",
                "Number of used reflections           =     22_467",
                "Invalid non-negative integer count token '22_467'",
            ),
            (
                "Overall R factor                     =     0.5207",
                "Overall R factor                     =    0_0.5207",
                "Invalid or nonfinite/sentinel R token '0_0.5207'",
            ),
        ):
            with self.subTest(replacement=replacement):
                mutated = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
                    target, replacement, 1
                )
                with self.assertRaisesRegex(ValueError, err_re):
                    parse_refmac_log(mutated)

    def test_graph_declaration_cycle_labels_validated_against_table_title(self) -> None:
        # 1. Final resolution R-factor $GRAPHS Cycle 31 -> Cycle 30 contradicts table title Cycle 31
        contradict_r_graph = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
            "$GRAPHS:Cycle   31. <Rfactor> v. resln :N:1,6,7,11,12:",
            "$GRAPHS:Cycle   30. <Rfactor> v. resln :N:1,6,7,11,12:",
        )
        with self.assertRaisesRegex(
            ValueError,
            r"Conflicting \$GRAPHS Cycle 30 .* vs resolution R-factor table title Cycle 31",
        ):
            parse_refmac_log(contradict_r_graph)

        # 2. Final resolution FOM $GRAPHS Cycle 31 -> Cycle 30 contradicts table title Cycle 31
        contradict_fom_graph = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
            " $GRAPHS:Cycle   31. M(Fom) v. resln :N:1,3,5,7,8:",
            " $GRAPHS:Cycle   30. M(Fom) v. resln :N:1,3,5,7,8:",
        )
        with self.assertRaisesRegex(
            ValueError,
            r"Conflicting \$GRAPHS Cycle 30 .* vs resolution FOM table title Cycle 31",
        ):
            parse_refmac_log(contradict_fom_graph)

        # 3. Continuation line :Cycle 31. -> :Cycle 30. contradicts table title Cycle 31
        contradict_cont_graph = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
            ":Cycle   31. <Fobs> and <Fc> v. resln :N:1,4,5,9,10:",
            ":Cycle   30. <Fobs> and <Fc> v. resln :N:1,4,5,9,10:",
        )
        with self.assertRaisesRegex(
            ValueError,
            r"Conflicting \$GRAPHS Cycle 30 .* vs resolution R-factor table title Cycle 31",
        ):
            parse_refmac_log(contradict_cont_graph)

        # 4. Malformed explicit Cycle labels in $GRAPHS or continuation lines rejected
        for bad_graph_line in (
            ":Cycle   31 <Fobs> and <Fc> v. resln :N:1,4,5,9,10:",
            ":cycle   31. <Fobs> and <Fc> v. resln :N:1,4,5,9,10:",
            ":Cycle  NaN. <Fobs> and <Fc> v. resln :N:1,4,5,9,10:",
            ":Cycle    0. <Fobs> and <Fc> v. resln :N:1,4,5,9,10:",
        ):
            with self.subTest(bad_graph_line=bad_graph_line):
                mutated = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
                    ":Cycle   31. <Fobs> and <Fc> v. resln :N:1,4,5,9,10:",
                    bad_graph_line,
                )
                with self.assertRaisesRegex(ValueError, r"\$GRAPHS"):
                    parse_refmac_log(mutated)

        # 5. Valid graph declaration without an explicit Cycle label is accepted
        no_cycle_in_graph = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "$GRAPHS:Cycle    1. <Rfactor> v. resln :N:1,6,7,11,12:",
            "$GRAPHS:<Rfactor> v. resln :N:1,6,7,11,12:",
        )
        parsed_no_graph_cycle = parse_refmac_log(no_cycle_in_graph)
        self.assertEqual(
            parsed_no_graph_cycle["reconciled_final_cycle"]["resolution_table_cycle"],
            1,
        )

    def test_fractional_negative_and_contradictory_counts_rejected(self) -> None:
        # 1. Fractional NR_used
        frac_nr_used = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            " 0.050    3100",
            " 0.050  3100.5",
        )
        with self.assertRaisesRegex(ValueError, "NR_used"):
            parse_refmac_log(frac_nr_used)

        # 2. Fractional NR_free
        frac_nr_free = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "     160    41.2",
            "   160.0    41.2",
        )
        with self.assertRaisesRegex(ValueError, "NR_free"):
            parse_refmac_log(frac_nr_free)

        # 3. Negative NR_used
        neg_nr_used = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            " 0.050    3100",
            " 0.050   -3100",
        )
        with self.assertRaisesRegex(ValueError, "NR_used"):
            parse_refmac_log(neg_nr_used)

        # 4. Negative NR_free
        neg_nr_free = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "     160    41.2",
            "      -1    41.2",
        )
        with self.assertRaisesRegex(ValueError, "NR_free"):
            parse_refmac_log(neg_nr_free)

        # 5. Fractional summary Ncyc
        frac_ncyc = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "       0   0.1912   0.2315",
            "     0.0   0.1912   0.2315",
        )
        with self.assertRaisesRegex(ValueError, "summary Ncyc"):
            parse_refmac_log(frac_ncyc)

        # 6. Contradictory Number of used reflections vs sum(NR_used)
        contradictory_used = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "Number of used reflections           =       6532",
            "Number of used reflections           =       6533",
        )
        with self.assertRaisesRegex(
            ValueError, "Number of used reflections .* != .* NR_used sum"
        ):
            parse_refmac_log(contradictory_used)

    def test_ambiguous_final_cycle_rejected(self) -> None:
        # 1. Wrong final resolution table cycle label (Cycle 30 instead of Cycle 31)
        wrong_final_table_cycle = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
            "$TABLE: Cycle   31. Rfactor analysis, F distribution v resln  :\n"
            "$GRAPHS:Cycle   31. <Rfactor> v. resln :N:1,6,7,11,12:\n"
            ":Cycle   31. <Fobs> and <Fc> v. resln :N:1,4,5,9,10:\n"
            ":Cycle   31. % observed v. resln :N:1,3:",
            "$TABLE: Cycle   30. Rfactor analysis, F distribution v resln  :\n"
            "$GRAPHS:Cycle   30. <Rfactor> v. resln :N:1,6,7,11,12:\n"
            ":Cycle   30. <Fobs> and <Fc> v. resln :N:1,4,5,9,10:\n"
            ":Cycle   30. % observed v. resln :N:1,3:",
        )
        with self.assertRaisesRegex(ValueError, "Resolution R-factor table Cycle 30"):
            parse_refmac_log(wrong_final_table_cycle)

        # 2. Missing final resolution R-factor table in multi-cycle log
        parts = HISTORICAL_AMPLE_EXCERPT_LOG.split(
            "$TABLE: Cycle   31. Rfactor analysis, F distribution v resln  :"
        )
        self.assertEqual(len(parts), 2)
        only_initial_resln_table = (
            parts[0]
            + "$TABLE: Cycle   31. Unrelated stats v resln :"
            + parts[1].replace(
                "M(4SSQ/LL) NR_used %_obs M(Fo_used) M(Fc_used) Rf_used WR_used\n"
                "NR_free M(Fo_free) M(Fc_free) Rf_free   WR_free $$",
                "C1 C2 C3 C4 C5 C6 C7 C8 C9 C10 C11 C12 $$",
                1,
            )
        )
        with self.assertRaisesRegex(
            ValueError, "Ambiguous or missing final resolution R-factor table"
        ):
            parse_refmac_log(only_initial_resln_table)

        # 3. Extra detailed Overall/Free R pair not in cycle_summary
        extra_detail_pair = HISTORICAL_AMPLE_EXCERPT_LOG.replace(
            "$TABLE: Rfactor analysis, stats vs cycle  :",
            "Overall R factor = 0.5207\nFree R factor = 0.5289\n"
            "-----------------------------------------------------------------------------\n"
            "$TABLE: Rfactor analysis, stats vs cycle  :",
        )
        with self.assertRaisesRegex(ValueError, "Cycle count mismatch"):
            parse_refmac_log(extra_detail_pair)

        # 4. Contradictory declared NCYC vs summary max Ncyc
        contradictory_ncyc = SYNTHETIC_SINGLE_CYCLE_NCYC0_LOG.replace(
            "  Data line--- NCYC 0\n  Refinement cycles       :     0",
            "  Data line--- NCYC 5\n  Refinement cycles       :     5",
        )
        with self.assertRaisesRegex(
            ValueError, "Cycle summary max Ncyc .* contradicts declared NCYC"
        ):
            parse_refmac_log(contradictory_ncyc)


if __name__ == "__main__":
    unittest.main()
