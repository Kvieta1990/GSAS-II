#!/usr/bin/env python
# -*- coding: utf-8 -*-
########### SVN repository information ###################
# $Date$
# $Author$
# $Revision$
# $URL$
# $Id$
########### SVN repository information ###################
'''
*Module G2export_CIF: CIF Exports*
------------------------------------------------------

This implements a complex exporter :class:`ExportCIF` that can implement an
entire project in a complete CIF intended for submission as a
publication. In addition, there are three subclasses of :class:`ExportCIF`:
:class:`ExportProjectCIF`,
:class:`ExportPhaseCIF` and :class:`ExportDataCIF` where extra parameters
for the _Exporter() determine if a project, single phase or data set are written.
'''

from __future__ import division, print_function
import platform
import datetime as dt
import os.path
import sys
import numpy as np
if '2' in platform.python_version_tuple()[0]:
    import cPickle as pickle
else:
    import pickle
import copy
import re
try:
    import wx
    import wx.lib.scrolledpanel as wxscroll
    import wx.lib.resizewidget as rw
except ImportError:
    # Avoid wx dependency for CLI
    class Placeholder(object):
        def __init__(self):
            self.BoxSizer = object
            self.Button = object
            self.Dialog = object
            self.ScrolledPanel = object
    wx = Placeholder()
    wxscroll = Placeholder()
import GSASIIpath
GSASIIpath.SetVersionNumber("$Revision$")
import GSASIIIO as G2IO
try:
    import GSASIIctrlGUI as G2G
except ImportError:
    pass
import GSASIIobj as G2obj
import GSASIImath as G2mth
import GSASIIspc as G2spc
import GSASIIlattice as G2lat
import GSASIIstrMain as G2stMn
import GSASIIstrIO as G2stIO        
import GSASIImapvars as G2mv
import GSASIIElem as G2el
import GSASIIpy3 as G2py3

DEBUG = False    #True to skip printing of reflection/powder profile lists

CIFdic = None

cellNames = ['length_a','length_b','length_c',
             'angle_alpha','angle_beta ','angle_gamma',
             'volume']
def striphist(var,insChar=''):
    'strip a histogram number from a var name'
    sv = var.split(':')
    if len(sv) <= 1: return var
    if sv[1]:
        sv[1] = insChar
    return ':'.join(sv)

def getCellwStrain(phasedict,seqData,pId,histname):
    'Get cell parameters and their errors for a sequential fit'
    #newCellDict = {}
    #if name in seqData and 'newCellDict' in seqData[histname]:
    #    newCellDict.update(seqData[histname]['newCellDict'])
    
    pfx = str(pId)+'::' # prefix for A values from phase
    Albls = [pfx+'A'+str(i) for i in range(6)]
    Avals = G2lat.cell2A(phasedict['General']['Cell'][1:7])
    #AiLookup = {}
    DijLookup = {}
    zeroDict = dict(zip(Avals,6*[0.,]))
    for i,v in enumerate(('D11','D22','D33','D12','D13','D23')):
        if pfx+v in seqData[histname]['newCellDict']:
            Avals[i] = seqData[histname]['newCellDict'][pfx+v][1]
            #AiLookup[seqData[histname]['newCellDict'][pfx+v][0]] = pfx+v
            DijLookup[pfx+v] = seqData[histname]['newCellDict'][pfx+v][0]
    covData = {  # relabeled with p:h:Dij as p::Ai
        'varyList': [DijLookup.get(striphist(v),v) for v in seqData[histname]['varyList']], 
        'covMatrix': seqData[histname]['covMatrix']}
    # apply symmetry
    cellDict = dict(zip(Albls,Avals))
    try:    # convert to direct cell
        A,zeros = G2stIO.cellFill(pfx,phasedict['General']['SGData'],cellDict,zeroDict)
        cell = list(G2lat.A2cell(A)) + [G2lat.calc_V(A)]
        cE = G2stIO.getCellEsd(pfx,phasedict['General']['SGData'],A,covData)
    except:
        cell = 7*[None]
        cE = 7*[None]
    return cell,cE

def mkSeqResTable(mode,seqHistList,seqData,Phases,Histograms,Controls):
    '''Setup sequential results table (based on code from 
    GSASIIseqGUI.UpdateSeqResults)

    TODO: This should be merged with the table build code in 
    GSASIIseqGUI.UpdateSeqResults and moved to somewhere non-GUI
    like GSASIIstrIO to create a single routine that can be used 
    in both places, but this means returning some 
    of the code that has been removed from there
    '''

    newAtomDict = seqData[seqHistList[0]].get('newAtomDict',{}) # dict with atom positions; relative & absolute
    atomLookup = {newAtomDict[item][0]:item for item in newAtomDict if item in seqData['varyList']}
    phaseLookup = {Phases[phase]['pId']:phase for phase in Phases}

    # make dict of varied cell parameters equivalents
    ESDlookup = {} # provides the Dij term for each Ak term (where terms are refined)
    Dlookup = {} # provides the Ak term for each Dij term (where terms are refined)
    newCellDict = {}
    for name in seqHistList:
        if name in seqData and 'newCellDict' in seqData[name]:
            newCellDict.update(seqData[name]['newCellDict'])
    cellAlist = []
    for item in newCellDict:
        cellAlist.append(newCellDict[item][0])
        if item in seqData.get('varyList',[]):
            ESDlookup[newCellDict[item][0]] = item
            Dlookup[item] = newCellDict[item][0]
    # add coordinate equivalents to lookup table
    for parm in atomLookup:
        Dlookup[atomLookup[parm]] = parm
        ESDlookup[parm] = atomLookup[parm]

    # get unit cell & symmetry for all phases & initial stuff for later use
    RecpCellTerms = {}
    SGdata = {}
    uniqCellIndx = {}
    #initialCell = {}
    RcellLbls = {}
    zeroDict = {}
    for phase in Phases:
        pId = Phases[phase]['pId']
        pfx = str(pId)+'::' # prefix for A values from phase
        RcellLbls[pId] = [pfx+'A'+str(i) for i in range(6)]
        RecpCellTerms[pId] = G2lat.cell2A(Phases[phase]['General']['Cell'][1:7])
        zeroDict[pId] = dict(zip(RcellLbls[pId],6*[0.,]))
        SGdata[pId] = Phases[phase]['General']['SGData']
        laue = SGdata[pId]['SGLaue']
        if laue == '2/m':
            laue += SGdata[pId]['SGUniq']
        for symlist,celllist in G2lat.UniqueCellByLaue:
            if laue in symlist:
                uniqCellIndx[pId] = celllist
                break
        else: # should not happen
            uniqCellIndx[pId] = list(range(6))
            
    # scan for locations where the variables change
    VaryListChanges = [] # histograms where there is a change
    combinedVaryList = []
    firstValueDict = {}
    vallookup = {}
    posdict = {}
    prevVaryList = []
    foundNames = []
    missing = 0
    for i,name in enumerate(seqHistList):
        if name not in seqData:
            if missing < 5:
                print(" Warning: "+name+" not found")
            elif missing == 5:
                print (' Warning: more are missing')
            missing += 1
            continue
        foundNames.append(name)
        maxPWL = 5
        for var,val,sig in zip(seqData[name]['varyList'],seqData[name]['variables'],seqData[name]['sig']):
            svar = striphist(var,'*') # wild-carded
            if 'PWL' in svar:
                if int(svar.split(':')[-1]) > maxPWL:
                    continue
            if svar not in combinedVaryList:
                # add variables to list as they appear
                combinedVaryList.append(svar)
                firstValueDict[svar] = (val,sig)
        if prevVaryList != seqData[name]['varyList']: # this refinement has a different refinement list from previous
            prevVaryList = seqData[name]['varyList']
            vallookup[name] = dict(zip(seqData[name]['varyList'],seqData[name]['variables']))
            posdict[name] = {}
            for var in seqData[name]['varyList']:
                svar = striphist(var,'*')
                if 'PWL' in svar:
                    if int(svar.split(':')[-1]) > maxPWL:
                        continue
                posdict[name][combinedVaryList.index(svar)] = svar
            VaryListChanges.append(name)
    if missing:
        print (' Warning: Total of %d data sets missing from sequential results'%(missing))

    #### --- start building table
    histNames = foundNames
#            sampleParms = GetSampleParms()
    nRows = len(histNames)
    tblValues = [list(range(nRows))]   # table of values arranged by columns
    tblSigs =   [None]                 # a list of sigma values, or None if not defined
    tblLabels = ['Number']             # a label for the column
    tblTypes = ['int']
    # start with Rwp values
    tblValues += [[seqData[name]['Rvals']['Rwp'] for name in histNames]]
    tblSigs += [None]
    tblLabels += ['Rwp']
    tblTypes += ['10,3']
    # add changing sample parameters to table
    sampleParmDict = {'Temperature':[],'Pressure':[],'Time':[],
                 'FreePrm1':[],'FreePrm2':[],'FreePrm3':[],'Omega':[],
                 'Chi':[],'Phi':[],'Azimuth':[],}
    for key in sampleParmDict:
        for h in histNames:
            var = ":" + str(Histograms[h]['hId']) + ":" + key
            sampleParmDict[key].append(seqData[h]['parmDict'].get(var))
        if not np.all(np.array(sampleParmDict[key]) == sampleParmDict[key][0]):
            tblValues += [sampleParmDict[key]]
            tblSigs.append(None)
            if 'FreePrm' in key and key in Controls:
                tblLabels.append(Controls[item])
            else:
                tblLabels.append(key)
            tblTypes += ['float']

    # add unique cell parameters  
    if len(newCellDict):
        for pId in sorted(RecpCellTerms):
            pfx = str(pId)+'::' # prefix for A values from phase
            cells = []
            cellESDs = []
            Albls = [pfx+'A'+str(i) for i in range(6)]
            for name in histNames:
                #if name not in Histograms: continue
                hId = Histograms[name]['hId']
                phfx = '%d:%d:'%(pId,hId)
                esdLookUp = {}
                dLookup = {}
                for item in seqData[name]['newCellDict']:
                    if phfx+item.split('::')[1] in seqData[name]['varyList']:
                        esdLookUp[newCellDict[item][0]] = item
                        dLookup[item] = newCellDict[item][0]
                covData = {'varyList': [dLookup.get(striphist(v),v) for v in seqData[name]['varyList']],
                    'covMatrix': seqData[name]['covMatrix']}
                A = RecpCellTerms[pId][:] # make copy of starting A values
                # update with refined values
                for i,j in enumerate(('D11','D22','D33','D12','D13','D23')):
                    var = str(pId)+'::A'+str(i)
                    Dvar = str(pId)+':'+str(hId)+':'+j
                    # apply Dij value if non-zero
                    if Dvar in seqData[name]['parmDict']:
                        parmDict = seqData[name]['parmDict']
                        if parmDict[Dvar] != 0.0:
                            A[i] += parmDict[Dvar]
                    # override with fit result if is Dij varied
                    if var in cellAlist:
                        try:
                            A[i] = seqData[name]['newCellDict'][esdLookUp[var]][1] # get refined value 
                        except KeyError:
                            pass
                # apply symmetry
                cellDict = dict(zip(Albls,A))
                try:    # convert to direct cell
                    A,zeros = G2stIO.cellFill(pfx,SGdata[pId],cellDict,zeroDict[pId])
                    c = G2lat.A2cell(A)
                    vol = G2lat.calc_V(A)
                    cE = G2stIO.getCellEsd(pfx,SGdata[pId],A,covData)
                except:
                    c = 6*[None]
                    cE = 6*[None]
                    vol = None
                # add only unique values to table
                if name in Phases[phaseLookup[pId]]['Histograms']:
                    cells += [[c[i] for i in uniqCellIndx[pId]]+[vol]]
                    cellESDs += [[cE[i] for i in uniqCellIndx[pId]]+[cE[-1]]]
                else:
                    cells += [[None for i in uniqCellIndx[pId]]+[None]]
                    cellESDs += [[None for i in uniqCellIndx[pId]]+[None]]
            p = phaseLookup[pId]
            tblLabels += ['{}, {}'.format(G2lat.cellAlbl[i],p) for i in uniqCellIndx[pId]]
            tblTypes += ['10,5' if i <3 else '10,3' for i in uniqCellIndx[pId]]
            tblLabels.append('{}, {}'.format('Volume',p))
            tblTypes += ['10,3']
            tblValues += zip(*cells)
            tblSigs += zip(*cellESDs)

    # sort out the variables in their selected order
    varcols = 0
    varlbls = []
    for d in posdict.values():
        varcols = max(varcols,max(d.keys())+1)
    # get labels for each column
    for i in range(varcols):
        lbl = ''
        for h in VaryListChanges:
            if posdict[h].get(i):
                if posdict[h].get(i) in lbl: continue
                if lbl != "": lbl += '/'
                lbl += posdict[h].get(i)
        varlbls.append(lbl)
    vals = []
    esds = []
    varsellist = None        # will be a list of variable names in the order they are selected to appear
    # tabulate values for each hist, leaving None for blank columns
    for name in histNames:
        if name in posdict:
            varsellist = [posdict[name].get(i) for i in range(varcols)]
            # translate variable names to how they will be used in the headings
            vs = [striphist(v,'*') for v in seqData[name]['varyList']]
            # determine the index for each column (or None) in the seqData[]['variables'] and ['sig'] lists
            sellist = [vs.index(v) if v is not None else None for v in varsellist]
            #sellist = [i if striphist(v,'*') in varsellist else None for i,v in enumerate(seqData[name]['varyList'])]
        if not varsellist: raise Exception()
        vals.append([seqData[name]['variables'][s] if s is not None else None for s in sellist])
        esds.append([seqData[name]['sig'][s] if s is not None else None for s in sellist])
    tblValues += zip(*vals)
    tblSigs += zip(*esds)
    tblLabels += varlbls
    tblTypes += ['float' for i in varlbls]
    
    # tabulate constrained variables, removing histogram numbers if needed
    # from parameter label
    depValDict = {}
    depSigDict = {}
    for name in histNames:
        for var in seqData[name].get('depParmDict',{}):
            val,sig = seqData[name]['depParmDict'][var]
            svar = striphist(var,'*')
            if svar not in depValDict:
               depValDict[svar] = [val]
               depSigDict[svar] = [sig]
            else:
               depValDict[svar].append(val)
               depSigDict[svar].append(sig)

    # add the dependent constrained variables to the table
    for var in sorted(depValDict):
        if len(depValDict[var]) != len(histNames): continue
        tblLabels.append(var)
        tblTypes.append('10,5')
        tblSigs += [depSigDict[var]]
        tblValues += [depValDict[var]]

    # add refined atom parameters to table
    for parm in sorted(atomLookup):
        tblLabels.append(parm)
        tblTypes.append('10,5')
        tblValues += [[seqData[name]['newAtomDict'][atomLookup[parm]][1] for name in histNames]]
        if atomLookup[parm] in seqData[histNames[0]]['varyList']:
            col = seqData[histNames[0]]['varyList'].index(atomLookup[parm])
            tblSigs += [[seqData[name]['sig'][col] for name in histNames]]
        else:
            tblSigs += [None]

    # compute and add weight fractions to table if varied
    for phase in Phases:
        var = str(Phases[phase]['pId'])+':*:Scale'
        if var not in combinedVaryList+list(depValDict.keys()): continue
        wtFrList = []
        sigwtFrList = []
        for i,name in enumerate(histNames):
            if name not in Phases[phase]['Histograms']:
                wtFrList.append(None)
                sigwtFrList.append(0.0)
                continue
            elif not Phases[phase]['Histograms'][name]['Use']:
                wtFrList.append(None)
                sigwtFrList.append(0.0)
                continue
            wtFrSum = 0.
            for phase1 in Phases:
                if name not in Phases[phase1]['Histograms']: continue
                if not Phases[phase1]['Histograms'][name]['Use']: continue
                wtFrSum += Phases[phase1]['Histograms'][name]['Scale'][0]*Phases[phase1]['General']['Mass']
            var = str(Phases[phase]['pId'])+':'+str(i)+':Scale'
            wtFr = Phases[phase]['Histograms'][name]['Scale'][0]*Phases[phase]['General']['Mass']/wtFrSum
            wtFrList.append(wtFr)
            if var in seqData[name]['varyList']:
                sig = seqData[name]['sig'][seqData[name]['varyList'].index(var)]*wtFr/Phases[phase]['Histograms'][name]['Scale'][0]
            elif var in seqData[name].get('depParmDict',{}):
                _,sig = seqData[name]['depParmDict'][var]
            else:
                sig = 0.0
            sigwtFrList.append(sig)
        p = phaseLookup[Phases[phase]['pId']]
        tblLabels.append(p + ' Wgt Frac')
        tblTypes.append('10,4')
        tblValues += [wtFrList]
        tblSigs += [sigwtFrList]
    return tblLabels,tblValues,tblSigs,tblTypes


# Refactored over here to allow access by GSASIIscriptable.py
def WriteCIFitem(fp, name, value=''):
    '''Helper function for writing CIF output. Translated from exports/G2export_CIF.py'''
    # Ignore unicode issues
    if value:
        if "\n" in value or len(value)> 70:
            if name.strip():
                fp.write(name+'\n')
            fp.write(';\n'+value+'\n')
            fp.write(';'+'\n')
        elif " " in value:
            if len(name)+len(value) > 65:
                fp.write(name + '\n   ' + '"' + str(value) + '"'+'\n')
            else:
                fp.write(name + '  ' + '"' + str(value) + '"'+'\n')
        else:
            if len(name)+len(value) > 65:
                fp.write(name+'\n   ' + value+'\n')
            else:
                fp.write(name+'  ' + value+'\n')
    else:
        fp.write(name+'\n')

def RBheader(fp):
    WriteCIFitem(fp,'\n# RIGID BODY DETAILS')
    WriteCIFitem(fp,'loop_\n    _restr_rigid_body_class.class_id\n    _restr_rigid_body_class.details')

# Refactored over here to allow access by GSASIIscriptable.py
def WriteAtomsNuclear(fp, phasedict, phasenam, parmDict, sigDict, labellist,
                          RBparms={}):
    'Write atom positions to CIF'
    # phasedict = self.Phases[phasenam] # pointer to current phase info
    General = phasedict['General']
    cx,ct,cs,cia = General['AtomPtrs']
    GS = G2lat.cell2GS(General['Cell'][1:7])
    Amat = G2lat.cell2AB(General['Cell'][1:7])[0]
    Atoms = phasedict['Atoms']
    cfrac = cx+3
    fpfx = str(phasedict['pId'])+'::Afrac:'
    for i,at in enumerate(Atoms):
        fval = parmDict.get(fpfx+str(i),at[cfrac])
        if fval != 0.0:
            break
    else:
        WriteCIFitem(fp, '\n# PHASE HAS NO ATOMS!')
        return

    WriteCIFitem(fp, '\n# ATOMIC COORDINATES AND DISPLACEMENT PARAMETERS')
    WriteCIFitem(fp, 'loop_ '+
                 '\n   _atom_site_label'+
                 '\n   _atom_site_type_symbol'+
                 '\n   _atom_site_fract_x'+
                 '\n   _atom_site_fract_y'+
                 '\n   _atom_site_fract_z'+
                 '\n   _atom_site_occupancy'+
                 '\n   _atom_site_adp_type'+
                 '\n   _atom_site_U_iso_or_equiv'+
                 '\n   _atom_site_site_symmetry_multiplicity')

    varnames = {cx:'Ax',cx+1:'Ay',cx+2:'Az',cx+3:'Afrac',
                cia+1:'AUiso',cia+2:'AU11',cia+3:'AU22',cia+4:'AU33',
                cia+5:'AU12',cia+6:'AU13',cia+7:'AU23'}
    # Empty the labellist
    while labellist:
        labellist.pop()

    pfx = str(phasedict['pId'])+'::'
    # loop over all atoms
    naniso = 0
    for i,at in enumerate(Atoms):
        if phasedict['General']['Type'] == 'macromolecular':
            label = '%s_%s_%s_%s'%(at[ct-1],at[ct-3],at[ct-4],at[ct-2])
            s = PutInCol(MakeUniqueLabel(label,labellist),15) # label
        else:
            s = PutInCol(MakeUniqueLabel(at[ct-1],labellist),6) # label
        fval = parmDict.get(fpfx+str(i),at[cfrac])
        if fval == 0.0: continue # ignore any atoms that have a occupancy set to 0 (exact)
        s += PutInCol(FmtAtomType(at[ct]),4) # type
        if at[cia] == 'I':
            adp = 'Uiso '
        else:
            adp = 'Uani '
            naniso += 1
            t = G2lat.Uij2Ueqv(at[cia+2:cia+8],GS,Amat)[0]
            for j in (2,3,4):
                var = pfx+varnames[cia+j]+":"+str(i)
        for j in (cx,cx+1,cx+2,cx+3,cia,cia+1):
            if j in (cx,cx+1,cx+2):
                dig = 11
                sigdig = -0.00009
            else:
                dig = 10
                sigdig = -0.0009
            if j == cia:
                s += adp
            else:
                var = pfx+varnames[j]+":"+str(i)
                dvar = pfx+"d"+varnames[j]+":"+str(i)
                if dvar not in sigDict:
                    dvar = var
                if j == cia+1 and adp == 'Uani ':
                    sig = sigdig
                    val = t
                else:
                    #print var,(var in parmDict),(var in sigDict)
                    val = parmDict.get(var,at[j])
                    sig = sigDict.get(dvar,sigdig)
                    if dvar in G2mv.GetDependentVars(): # do not include an esd for dependent vars
                        sig = -abs(sig)
                s += PutInCol(G2mth.ValEsd(val,sig),dig)
        s += PutInCol(at[cs+1],3)
        WriteCIFitem(fp, s)
    if naniso != 0: 
        # now loop over aniso atoms
        WriteCIFitem(fp, '\nloop_' + '\n   _atom_site_aniso_label' +
                     '\n   _atom_site_aniso_U_11' + '\n   _atom_site_aniso_U_22' +
                     '\n   _atom_site_aniso_U_33' + '\n   _atom_site_aniso_U_12' +
                     '\n   _atom_site_aniso_U_13' + '\n   _atom_site_aniso_U_23')
        for i,at in enumerate(Atoms):
            fval = parmDict.get(fpfx+str(i),at[cfrac])
            if fval == 0.0: continue # ignore any atoms that have a occupancy set to 0 (exact)
            if at[cia] == 'I': continue
            s = PutInCol(labellist[i],6) # label
            for j in (2,3,4,5,6,7):
                sigdig = -0.0009
                var = pfx+varnames[cia+j]+":"+str(i)
                val = parmDict.get(var,at[cia+j])
                sig = sigDict.get(var,sigdig)
                s += PutInCol(G2mth.ValEsd(val,sig),11)
            WriteCIFitem(fp, s)
    # save information about rigid bodies
    header = False
    num = 0
    rbAtoms = []
    for irb,RBObj in enumerate(phasedict['RBModels'].get('Residue',[])):
        if not header:
            header = True
            RBheader(fp)
        jrb = RBparms['RBIds']['Residue'].index(RBObj['RBId'])
        rbsx = str(irb)+':'+str(jrb)
        num += 1
        WriteCIFitem(fp,'',str(num))
        RBModel = RBparms['Residue'][RBObj['RBId']]
        SGData = phasedict['General']['SGData']
        Sytsym,Mult = G2spc.SytSym(RBObj['Orig'][0],SGData)[:2]
        s = '''GSAS-II residue rigid body "{}" with {} atoms
  Site symmetry @ origin: {}, multiplicity: {}
'''.format(RBObj['RBname'],len(RBModel['rbTypes']),Sytsym,Mult)
        for i in G2stIO.WriteResRBModel(RBModel):
            s += i
        s += '\n Location:\n'
        for i in G2stIO.WriteRBObjPOAndSig(pfx,'RBR',rbsx,parmDict,sigDict):
            s += i+'\n'
        for i in G2stIO.WriteRBObjTLSAndSig(pfx,'RBR',rbsx,
                        RBObj['ThermalMotion'][0],parmDict,sigDict):
            s += i
        nTors = len(RBObj['Torsions'])
        if nTors:
            for i in G2stIO.WriteRBObjTorAndSig(pfx,rbsx,parmDict,sigDict,
                        nTors):
                s += i
        WriteCIFitem(fp,'',s.rstrip())
        
        pId = phasedict['pId']
        for i in RBObj['Ids']:
            lbl = G2obj.LookupAtomLabel(pId,G2obj.LookupAtomId(pId,i))[0]
            rbAtoms.append('{:7s} 1_555 {:3d} ?'.format(lbl,num))
        #GSASIIpath.IPyBreak()

    for irb,RBObj in enumerate(phasedict['RBModels'].get('Vector',[])):
        if not header:
            header = True
            RBheader(fp)
        jrb = RBparms['RBIds']['Vector'].index(RBObj['RBId'])
        rbsx = str(irb)+':'+str(jrb)
        num += 1
        WriteCIFitem(fp,'',str(num))
        RBModel = RBparms['Vector'][RBObj['RBId']]
        SGData = phasedict['General']['SGData']
        Sytsym,Mult = G2spc.SytSym(RBObj['Orig'][0],SGData)[:2]
        s = '''GSAS-II vector rigid body "{}" with {} atoms
  Site symmetry @ origin: {}, multiplicity: {}
'''.format(RBObj['RBname'],len(RBModel['rbTypes']),Sytsym,Mult)
        for i in G2stIO.WriteVecRBModel(RBModel,sigDict,irb):
            s += i
        s += '\n Location:\n'
        for i in G2stIO.WriteRBObjPOAndSig(pfx,'RBV',rbsx,parmDict,sigDict):
            s += i+'\n'
        for i in G2stIO.WriteRBObjTLSAndSig(pfx,'RBV',rbsx,
                        RBObj['ThermalMotion'][0],parmDict,sigDict):
            s += i
        WriteCIFitem(fp,'',s.rstrip())
        
        pId = phasedict['pId']
        for i in RBObj['Ids']:
            lbl = G2obj.LookupAtomLabel(pId,G2obj.LookupAtomId(pId,i))[0]
            rbAtoms.append('{:7s} 1_555 {:3d} ?'.format(lbl,num))

    if rbAtoms:
        WriteCIFitem(fp,'loop_\n    _restr_rigid_body.id'+
            '\n    _restr_rigid_body.atom_site_label\n    _restr_rigid_body.site_symmetry'+
            '\n    _restr_rigid_body.class_id\n    _restr_rigid_body.details')
        for i,l in enumerate(rbAtoms):
            WriteCIFitem(fp,'   {:5d} {}'.format(i+1,l))
            
def WriteAtomsMagnetic(fp, phasedict, phasenam, parmDict, sigDict, labellist):
    'Write atom positions to CIF'
    # phasedict = self.Phases[phasenam] # pointer to current phase info
    General = phasedict['General']
    cx,ct,cs,cia = General['AtomPtrs']
    Atoms = phasedict['Atoms']
    cfrac = cx+3
    fpfx = str(phasedict['pId'])+'::Afrac:'
    for i,at in enumerate(Atoms):
        fval = parmDict.get(fpfx+str(i),at[cfrac])
        if fval != 0.0:
            break
    else:
        WriteCIFitem(fp, '\n# PHASE HAS NO ATOMS!')
        return

    WriteCIFitem(fp, '\n# ATOMIC COORDINATES AND DISPLACEMENT PARAMETERS')
    WriteCIFitem(fp, 'loop_ '+
                 '\n   _atom_site_label'+
                 '\n   _atom_site_type_symbol'+
                 '\n   _atom_site_fract_x'+
                 '\n   _atom_site_fract_y'+
                 '\n   _atom_site_fract_z'+
                 '\n   _atom_site_occupancy'+
                 '\n   _atom_site_adp_type'+
                 '\n   _atom_site_U_iso_or_equiv'+
                 '\n   _atom_site_site_symmetry_multiplicity')

    varnames = {cx:'Ax',cx+1:'Ay',cx+2:'Az',cx+3:'Afrac',
                cx+4:'AMx',cx+5:'AMy',cx+6:'AMz',
                cia+1:'AUiso',cia+2:'AU11',cia+3:'AU22',cia+4:'AU33',
                cia+5:'AU12',cia+6:'AU13',cia+7:'AU23'}
    # Empty the labellist
    while labellist:
        labellist.pop()

    pfx = str(phasedict['pId'])+'::'
    # loop over all atoms
    naniso = 0
    for i,at in enumerate(Atoms):
        if phasedict['General']['Type'] == 'macromolecular':
            label = '%s_%s_%s_%s'%(at[ct-1],at[ct-3],at[ct-4],at[ct-2])
            s = PutInCol(MakeUniqueLabel(label,labellist),15) # label
        else:
            s = PutInCol(MakeUniqueLabel(at[ct-1],labellist),6) # label
        fval = parmDict.get(fpfx+str(i),at[cfrac])
        if fval == 0.0: continue # ignore any atoms that have a occupancy set to 0 (exact)
        s += PutInCol(FmtAtomType(at[ct]),4) # type
        if at[cia] == 'I':
            adp = 'Uiso '
        else:
            adp = 'Uani '
            naniso += 1
            # compute Uequiv crudely
            # correct: Defined as "1/3 trace of diagonalized U matrix".
            # SEE cell2GS & Uij2Ueqv to GSASIIlattice. Former is needed to make the GS matrix used by the latter.
            t = 0.0
            for j in (2,3,4):
                var = pfx+varnames[cia+j]+":"+str(i)
                t += parmDict.get(var,at[cia+j])
        for j in (cx,cx+1,cx+2,cx+3,cia,cia+1):
            if j in (cx,cx+1,cx+2):
                dig = 11
                sigdig = -0.00009
            else:
                dig = 10
                sigdig = -0.009
            if j == cia:
                s += adp
            else:
                var = pfx+varnames[j]+":"+str(i)
                dvar = pfx+"d"+varnames[j]+":"+str(i)
                if dvar not in sigDict:
                    dvar = var
                if j == cia+1 and adp == 'Uani ':
                    val = t/3.
                    sig = sigdig
                else:
                    #print var,(var in parmDict),(var in sigDict)
                    val = parmDict.get(var,at[j])
                    sig = sigDict.get(dvar,sigdig)
                    if dvar in G2mv.GetDependentVars(): # do not include an esd for dependent vars
                        sig = -abs(sig)
                s += PutInCol(G2mth.ValEsd(val,sig),dig)
        s += PutInCol(at[cs+1],3)
        WriteCIFitem(fp, s)
    if naniso: 
        # now loop over aniso atoms
        WriteCIFitem(fp, '\nloop_' + '\n   _atom_site_aniso_label' +
                     '\n   _atom_site_aniso_U_11' + '\n   _atom_site_aniso_U_22' +
                     '\n   _atom_site_aniso_U_33' + '\n   _atom_site_aniso_U_12' +
                     '\n   _atom_site_aniso_U_13' + '\n   _atom_site_aniso_U_23')
        for i,at in enumerate(Atoms):
            fval = parmDict.get(fpfx+str(i),at[cfrac])
            if fval == 0.0: continue # ignore any atoms that have a occupancy set to 0 (exact)
            if at[cia] == 'I': continue
            s = PutInCol(labellist[i],6) # label
            for j in (2,3,4,5,6,7):
                sigdig = -0.0009
                var = pfx+varnames[cia+j]+":"+str(i)
                val = parmDict.get(var,at[cia+j])
                sig = sigDict.get(var,sigdig)
                s += PutInCol(G2mth.ValEsd(val,sig),11)
            WriteCIFitem(fp, s)
    # now loop over mag atoms (e.g. all of them)
    WriteCIFitem(fp, '\nloop_' + '\n   _atom_site_moment.label' +
                 '\n   _atom_site_moment.crystalaxis_x' +
                 '\n   _atom_site_moment.crystalaxis_y' +
                 '\n   _atom_site_moment.crystalaxis_z')
    for i,at in enumerate(Atoms):
        fval = parmDict.get(fpfx+str(i),at[cfrac])
        if fval == 0.0: continue # ignore any atoms that have a occupancy set to 0 (exact)
        s = PutInCol(labellist[i],6) # label
        for j in (cx+4,cx+5,cx+6):
            sigdig = -0.0009
            var = pfx+varnames[j]+":"+str(i)
            val = parmDict.get(var,at[j])
            sig = sigDict.get(var,sigdig)
            s += PutInCol(G2mth.ValEsd(val,sig),11)
        WriteCIFitem(fp, s)

# Refactored over here to allow access by GSASIIscriptable.py
def WriteSeqAtomsNuclear(fp, cell, phasedict, phasenam, hist, seqData, RBparms):
    'Write atom positions to CIF'
    General = phasedict['General']
    cx,ct,cs,cia = General['AtomPtrs']
    GS = G2lat.cell2GS(cell[:6])
    Amat = G2lat.cell2AB(cell[:6])[0]

    # phasedict = self.Phases[phasenam] # pointer to current phase info
    parmDict = seqData[hist]['parmDict']
    sigDict = dict(zip(seqData[hist]['varyList'],seqData[hist]['sig']))
    Atoms = phasedict['Atoms']
    cfrac = cx+3
    fpfx = str(phasedict['pId'])+'::Afrac:'
    for i,at in enumerate(Atoms):
        fval = parmDict.get(fpfx+str(i),at[cfrac])
        if fval != 0.0:
            break
    else:
        WriteCIFitem(fp, '\n# PHASE HAS NO ATOMS!')
        return

    WriteCIFitem(fp, '\n# ATOMIC COORDINATES AND DISPLACEMENT PARAMETERS')
    WriteCIFitem(fp, 'loop_ '+
                 '\n   _atom_site_label'+
                 '\n   _atom_site_type_symbol'+
                 '\n   _atom_site_fract_x'+
                 '\n   _atom_site_fract_y'+
                 '\n   _atom_site_fract_z'+
                 '\n   _atom_site_occupancy'+
                 '\n   _atom_site_adp_type'+
                 '\n   _atom_site_U_iso_or_equiv'+
                 '\n   _atom_site_site_symmetry_multiplicity')

    varnames = {cx:'Ax',cx+1:'Ay',cx+2:'Az',cx+3:'Afrac',
                cia+1:'AUiso',cia+2:'AU11',cia+3:'AU22',cia+4:'AU33',
                cia+5:'AU12',cia+6:'AU13',cia+7:'AU23'}

    labellist = []  # used to make atom labels unique as required in CIF
    pfx = str(phasedict['pId'])+'::'
    # loop over all atoms
    naniso = 0

    for i,at in enumerate(Atoms):
        if phasedict['General']['Type'] == 'macromolecular':
            label = '%s_%s_%s_%s'%(at[ct-1],at[ct-3],at[ct-4],at[ct-2])
            s = PutInCol(MakeUniqueLabel(label,labellist),15) # label
        else:
            s = PutInCol(MakeUniqueLabel(at[ct-1],labellist),6) # label
        fval = parmDict.get(fpfx+str(i),at[cfrac])
        if fval == 0.0: continue # ignore any atoms that have a occupancy set to 0 (exact)
        s += PutInCol(FmtAtomType(at[ct]),4) # type
        if at[cia] == 'I':
            adp = 'Uiso '
        else:
            adp = 'Uani '
            naniso += 1
            t = G2lat.Uij2Ueqv(at[cia+2:cia+8],GS,Amat)[0]
            for j in (2,3,4):
                var = pfx+varnames[cia+j]+":"+str(i)
        for j in (cx,cx+1,cx+2,cx+3,cia,cia+1):
            if j in (cx,cx+1,cx+2):
                dig = 11
                sigdig = -0.00009
            else:
                dig = 10
                sigdig = -0.0009
            if j == cia:
                s += adp
            else:
                var = pfx+varnames[j]+":"+str(i)
                dvar = pfx+"d"+varnames[j]+":"+str(i)
                if dvar not in sigDict:
                    dvar = var
                if j == cia+1 and adp == 'Uani ':
                    sig = sigdig
                    val = t
                else:
                    #print var,(var in parmDict),(var in sigDict)
                    val = parmDict.get(var,at[j])
                    sig = sigDict.get(dvar,sigdig)
                    if dvar in G2mv.GetDependentVars(): # do not include an esd for dependent vars
                        sig = -abs(sig)
                s += PutInCol(G2mth.ValEsd(val,sig),dig)
        s += PutInCol(at[cs+1],3)
        WriteCIFitem(fp, s)
    if naniso != 0: 
        # now loop over aniso atoms
        WriteCIFitem(fp, '\nloop_' + '\n   _atom_site_aniso_label' +
                     '\n   _atom_site_aniso_U_11' + '\n   _atom_site_aniso_U_22' +
                     '\n   _atom_site_aniso_U_33' + '\n   _atom_site_aniso_U_12' +
                     '\n   _atom_site_aniso_U_13' + '\n   _atom_site_aniso_U_23')
        for i,at in enumerate(Atoms):
            fval = parmDict.get(fpfx+str(i),at[cfrac])
            if fval == 0.0: continue # ignore any atoms that have a occupancy set to 0 (exact)
            if at[cia] == 'I': continue
            s = PutInCol(labellist[i],6) # label
            for j in (2,3,4,5,6,7):
                sigdig = -0.0009
                var = pfx+varnames[cia+j]+":"+str(i)
                val = parmDict.get(var,at[cia+j])
                sig = sigDict.get(var,sigdig)
                s += PutInCol(G2mth.ValEsd(val,sig),11)
            WriteCIFitem(fp, s)
    # save information about rigid bodies
    header = False
    num = 0
    rbAtoms = []
    for irb,RBObj in enumerate(phasedict['RBModels'].get('Residue',[])):
        if not header:
            header = True
            RBheader(fp)
        jrb = RBparms['RBIds']['Residue'].index(RBObj['RBId'])
        rbsx = str(irb)+':'+str(jrb)
        num += 1
        WriteCIFitem(fp,'',str(num))
        RBModel = RBparms['Residue'][RBObj['RBId']]
        SGData = phasedict['General']['SGData']
        Sytsym,Mult = G2spc.SytSym(RBObj['Orig'][0],SGData)[:2]
        s = '''GSAS-II residue rigid body "{}" with {} atoms
  Site symmetry @ origin: {}, multiplicity: {}
'''.format(RBObj['RBname'],len(RBModel['rbTypes']),Sytsym,Mult)
        for i in G2stIO.WriteResRBModel(RBModel):
            s += i
        s += '\n Location:\n'
        for i in G2stIO.WriteRBObjPOAndSig(pfx,'RBR',rbsx,parmDict,sigDict):
            s += i+'\n'
        for i in G2stIO.WriteRBObjTLSAndSig(pfx,'RBR',rbsx,
                        RBObj['ThermalMotion'][0],parmDict,sigDict):
            s += i
        nTors = len(RBObj['Torsions'])
        if nTors:
            for i in G2stIO.WriteRBObjTorAndSig(pfx,rbsx,parmDict,sigDict,
                        nTors):
                s += i
        WriteCIFitem(fp,'',s.rstrip())
        
        pId = phasedict['pId']
        for i in RBObj['Ids']:
            lbl = G2obj.LookupAtomLabel(pId,G2obj.LookupAtomId(pId,i))[0]
            rbAtoms.append('{:7s} 1_555 {:3d} ?'.format(lbl,num))
        #GSASIIpath.IPyBreak()

    for irb,RBObj in enumerate(phasedict['RBModels'].get('Vector',[])):
        if not header:
            header = True
            RBheader(fp)
        jrb = RBparms['RBIds']['Vector'].index(RBObj['RBId'])
        rbsx = str(irb)+':'+str(jrb)
        num += 1
        WriteCIFitem(fp,'',str(num))
        RBModel = RBparms['Vector'][RBObj['RBId']]
        SGData = phasedict['General']['SGData']
        Sytsym,Mult = G2spc.SytSym(RBObj['Orig'][0],SGData)[:2]
        s = '''GSAS-II vector rigid body "{}" with {} atoms
  Site symmetry @ origin: {}, multiplicity: {}
'''.format(RBObj['RBname'],len(RBModel['rbTypes']),Sytsym,Mult)
        for i in G2stIO.WriteVecRBModel(RBModel,sigDict,irb):
            s += i
        s += '\n Location:\n'
        for i in G2stIO.WriteRBObjPOAndSig(pfx,'RBV',rbsx,parmDict,sigDict):
            s += i+'\n'
        for i in G2stIO.WriteRBObjTLSAndSig(pfx,'RBV',rbsx,
                        RBObj['ThermalMotion'][0],parmDict,sigDict):
            s += i
        WriteCIFitem(fp,'',s.rstrip())
        
        pId = phasedict['pId']
        for i in RBObj['Ids']:
            lbl = G2obj.LookupAtomLabel(pId,G2obj.LookupAtomId(pId,i))[0]
            rbAtoms.append('{:7s} 1_555 {:3d} ?'.format(lbl,num))

    if rbAtoms:
        WriteCIFitem(fp,'loop_\n    _restr_rigid_body.id'+
            '\n    _restr_rigid_body.atom_site_label\n    _restr_rigid_body.site_symmetry'+
            '\n    _restr_rigid_body.class_id\n    _restr_rigid_body.details')
        for i,l in enumerate(rbAtoms):
            WriteCIFitem(fp,'   {:5d} {}'.format(i+1,l))
            
# Refactored over here to allow access by GSASIIscriptable.py
def MakeUniqueLabel(lbl, labellist):
    lbl = lbl.strip()
    if not lbl: # deal with a blank label
        lbl = 'A_1'
    if lbl not in labellist:
        labellist.append(lbl)
        return lbl
    i = 1
    prefix = lbl
    if '_' in lbl:
        prefix = lbl[:lbl.rfind('_')]
        suffix = lbl[lbl.rfind('_')+1:]
        try:
            i = int(suffix)+1
        except:
            pass
    while prefix+'_'+str(i) in labellist:
        i += 1
    else:
        lbl = prefix+'_'+str(i)
        labellist.append(lbl)


# Refactored over here to allow access by GSASIIscriptable.py
def HillSortElements(elmlist):
    '''Sort elements in "Hill" order: C, H, others, (where others
    are alphabetical).

    :params list elmlist: a list of element strings

    :returns: a sorted list of element strings
    '''
    newlist = []
    oldlist = elmlist[:]
    for elm in ('C','H'):
        if elm in elmlist:
            newlist.append(elm)
            oldlist.pop(oldlist.index(elm))
    return newlist+sorted(oldlist)


def FmtAtomType(sym):
    'Reformat a GSAS-II atom type symbol to match CIF rules'
    sym = sym.replace('_','') # underscores are not allowed: no isotope designation?
    # in CIF, oxidation state sign symbols come after, not before
    if '+' in sym:
        sym = sym.replace('+','') + '+'
    elif '-' in sym:
        sym = sym.replace('-','') + '-'
    return sym


def PutInCol(val, wid):
    val = str(val).replace(' ', '')
    if not val: val = '?'
    fmt = '{:' + str(wid) + '} '
    try:
        return fmt.format(val)
    except TypeError:
        return fmt.format('.')


# Refactored over here to allow access by GSASIIscriptable.py
def WriteComposition(fp, phasedict, phasenam, parmDict, quickmode=True, keV=None):
    '''determine the composition for the unit cell, crudely determine Z and
    then compute the composition in formula units.

    If quickmode is False, then scattering factors are added to the element loop.

    If keV is specified, then resonant scattering factors are also computed and included. 
    '''
    General = phasedict['General']
    Z = General.get('cellZ',0.0)
    cx,ct,cs,cia = General['AtomPtrs']
    Atoms = phasedict['Atoms']
    fpfx = str(phasedict['pId'])+'::Afrac:'
    cfrac = cx+3
    cmult = cs+1
    compDict = {} # combines H,D & T
    sitemultlist = []
    massDict = dict(zip(General['AtomTypes'],General['AtomMass']))
    cellmass = 0
    elmLookup = {}
    for i,at in enumerate(Atoms):
        atype = at[ct].strip()
        if atype.find('-') != -1: atype = atype.split('-')[0]
        if atype.find('+') != -1: atype = atype.split('+')[0]
        atype = atype[0].upper()+atype[1:2].lower() # force case conversion
        if atype == "D" or atype == "D": atype = "H"
        fvar = fpfx+str(i)
        fval = parmDict.get(fvar,at[cfrac])
        mult = at[cmult]
        if not massDict.get(at[ct]):
            print('Error: No mass found for atom type '+at[ct])
            print('Will not compute cell contents for phase '+phasenam)
            return
        cellmass += massDict[at[ct]]*mult*fval
        compDict[atype] = compDict.get(atype,0.0) + mult*fval
        elmLookup[atype] = at[ct].strip()
        if fval == 1: sitemultlist.append(mult)
    if len(compDict.keys()) == 0: return # no elements!
    if Z < 1: # Z has not been computed or set by user
        Z = 1
        if not sitemultlist:
            General['cellZ'] = 1
            return
        for i in range(2,min(sitemultlist)+1):
            for m in sitemultlist:
                if m % i != 0:
                    break
                else:
                    Z = i
        General['cellZ'] = Z # save it

    if not quickmode:
        FFtable = G2el.GetFFtable(General['AtomTypes'])
        BLtable = G2el.GetBLtable(General)

    WriteCIFitem(fp, '\nloop_  _atom_type_symbol _atom_type_number_in_cell')
    s = '       '
    if not quickmode:
        for j in ('a1','a2','a3','a4','b1','b2','b3','b4','c',2,1):
            if len(s) > 80:
                WriteCIFitem(fp, s)
                s = '       '
            if j==1:
                s += ' _atom_type_scat_source'
            elif j==2:
                s += ' _atom_type_scat_length_neutron'
            else:
                s += ' _atom_type_scat_Cromer_Mann_'
                s += j
        if keV:
            WriteCIFitem(fp, s)
            s = '        _atom_type_scat_dispersion_real _atom_type_scat_dispersion_imag _atom_type_scat_dispersion_source'
        WriteCIFitem(fp, s)

            
    formula = ''
    for elem in HillSortElements(list(compDict.keys())):
        s = '  '
        elmsym = elmLookup[elem]
        # CIF does not allow underscore in element symbol (https://www.iucr.org/__data/iucr/cifdic_html/1/cif_core.dic/Iatom_type_symbol.html)
        if elmsym.endswith("_"):
             s += PutInCol(elmsym.replace('_',''))
        elif '_' in elmsym:
             s += PutInCol(elmsym.replace('_','~'))
        else:
            s += PutInCol(elmsym,7)
        s += PutInCol(G2mth.ValEsd(compDict[elem],-0.009,True),5)
        if not quickmode:
            for i in 'fa','fb','fc':
                if i != 'fc':
                    for j in range(4):
                        if elmsym in FFtable:
                            val = G2mth.ValEsd(FFtable[elmsym][i][j],-0.0009,True)
                        else:
                            val = '?'
                        s += ' '
                        s += PutInCol(val,9)
                else:
                    if elmsym in FFtable:
                        val = G2mth.ValEsd(FFtable[elmsym][i],-0.0009,True)
                    else:
                        val = '?'
                    s += ' '
                    s += PutInCol(val,9)
            if elmsym in BLtable:
                bldata = BLtable[elmsym]
                #isotope = bldata[0]
                #mass = bldata[1]['Mass']
                if 'BW-LS' in bldata[1]:
                    val = 0
                else:
                    val = G2mth.ValEsd(bldata[1]['SL'][0],-0.0009,True)
            else:
                val = '?'
            s += ' '
            s += PutInCol(val,9)
            WriteCIFitem(fp,s.rstrip())
            WriteCIFitem(fp,'      https://subversion.xray.aps.anl.gov/pyGSAS/trunk/atmdata.py')
            if keV:
                Orbs = G2el.GetXsectionCoeff(elem.split('+')[0].split('-')[0])
                FP,FPP,Mu = G2el.FPcalc(Orbs, keV)
                WriteCIFitem(fp,'  {:8.3f}{:8.3f}   https://subversion.xray.aps.anl.gov/pyGSAS/trunk/atmdata.py'.format(FP,FPP))
        else:
            WriteCIFitem(fp,s.rstrip())
        if formula: formula += " "
        formula += elem
        if compDict[elem] == Z: continue
        formula += G2mth.ValEsd(compDict[elem]/Z,-0.009,True)
    WriteCIFitem(fp,  '\n# Note that Z affects _cell_formula_sum and _weight')
    WriteCIFitem(fp,  '_cell_formula_units_Z',str(Z))
    WriteCIFitem(fp,  '_chemical_formula_sum',formula)
    WriteCIFitem(fp,  '_chemical_formula_weight',
                  G2mth.ValEsd(cellmass/Z,-0.09,True))

class ExportCIF(G2IO.ExportBaseclass):
    '''Base class for CIF exports
    '''
    def __init__(self,G2frame,formatName,extension,longFormatName=None,):
        G2IO.ExportBaseclass.__init__(self,G2frame,formatName,extension,longFormatName=None)
        self.exporttype = []
        self.author = ''
        self.CIFname = ''

    def ValidateAscii(self,checklist):
        '''Validate items as ASCII'''
        msg = ''
        for lbl,val in checklist:
            if not all(ord(c) < 128 for c in val):
                if msg: msg += '\n'
                msg += lbl + " contains unicode characters: " + val
        if msg:
            G2G.G2MessageBox(self.G2frame,
                             'Error: CIFs can contain only ASCII characters. Please change item(s) below:\n\n'+msg,
                             'Unicode not valid for CIF')
            return True

    def _CellSelectNeeded(self,phasenam):
        '''Determines if selection is needed for a T value in a multiblock CIF

        :returns: True if the choice of T is ambiguous and a human should
          be asked. 
        '''
        phasedict = self.Phases[phasenam] # pointer to current phase info
        Tlist = {}  # histname & T values used for cell w/o Hstrain
        DijTlist = {} # hId & T values used for cell w/Hstrain
        # scan over histograms used in this phase to determine the best
        # data collection T value
        for h in phasedict['Histograms']:
            if not phasedict['Histograms'][h]['Use']: continue
            if 'Flack' in phasedict['Histograms'][h].keys():       #single crystal data
                return False
            T = self.Histograms[h]['Sample Parameters']['Temperature']
            if np.any(abs(np.array(phasedict['Histograms'][h]['HStrain'][0])) > 1e-8):
                DijTlist[h] = T
            else:
                Tlist[h] = T
        if len(Tlist) > 0:
            T = sum(Tlist.values())/len(Tlist)
            if max(Tlist.values()) - T > 1:
                return True # temperatures span more than 1 degree, user needs to pick one
            return False
        elif len(DijTlist) == 1:
            return False
        elif len(DijTlist) > 1:
                # each histogram has different cell lengths, user needs to pick one
            return True
        
    def _CellSelectHist(self,phasenam):
        '''Select T value for a phase in a multiblock CIF

        :returns: T,h_ranId where T is a temperature (float) or '?' and
          h_ranId is the random Id (ranId) for a histogram in the 
          current phase. This is stored in OverallParms['Controls']['CellHistSelection']
        '''
        phasedict = self.Phases[phasenam] # pointer to current phase info
        Tlist = {}  # histname & T values used for cell w/o Hstrain
        DijTlist = {} # hId & T values used for cell w/Hstrain
        # scan over histograms used in this phase to determine the best
        # data collection T value
        for h in phasedict['Histograms']:
            if not phasedict['Histograms'][h]['Use']: continue
            if 'Flack' in phasedict['Histograms'][h].keys():       #single crystal data
                return (300,None)
            T = self.Histograms[h]['Sample Parameters']['Temperature']
            if np.any(abs(np.array(phasedict['Histograms'][h]['HStrain'][0])) > 1e-8):
                DijTlist[h] = T
            else:
                Tlist[h] = T
        if len(Tlist) > 0:
            T = sum(Tlist.values())/len(Tlist)
            if max(Tlist.values()) - T > 1:
                # temperatures span more than 1 degree, user needs to pick one
                choices = ["{} (unweighted average)".format(T)]
                Ti = [T]
                for h in Tlist:
                    choices += ["{} (hist {})".format(Tlist[h],h)]
                    Ti += [Tlist[h]]                            
                msg = 'The cell parameters for phase {} are from\nhistograms with different temperatures.\n\nSelect a T value below'.format(phasenam)
                dlg = wx.SingleChoiceDialog(self.G2frame,msg,'Select T',choices)
                if dlg.ShowModal() == wx.ID_OK:
                    T = Ti[dlg.GetSelection()]
                else:
                    T = '?'
                dlg.Destroy()
            return (T,None)
        elif len(DijTlist) == 1:
            h = list(DijTlist.keys())[0]
            h_ranId = self.Histograms[h]['ranId']
            return (DijTlist[h],h_ranId)
        elif len(DijTlist) > 1:
            # each histogram has different cell lengths, user needs to pick one
            choices = []
            hi = []
            for h in DijTlist:
                choices += ["{} (hist {})".format(DijTlist[h],h)]
                hi += [h]
            msg = 'There are {} sets of cell parameters for phase {}\n due to refined Hstrain values.\n\nSelect the histogram to use with the phase form list below'.format(len(DijTlist),phasenam)
            dlg = wx.SingleChoiceDialog(self.G2frame,msg,'Select cell',choices)
            if dlg.ShowModal() == wx.ID_OK:
                h = hi[dlg.GetSelection()] 
                h_ranId = self.Histograms[h]['ranId']
                T = DijTlist[h]
            else:
                T = '?'
                h_ranId = None
            dlg.Destroy()
            return (T,h_ranId)
        else:
            print('Unexpected option in _CellSelectHist for',phasenam)
            return ('?',None)

    def ShowHstrainCells(self,phasenam,datablockidDict):
        '''Displays the unit cell parameters for phases where Dij values create 
        mutiple sets of lattice parameters. At present there is no way defined for this in 
        CIF, so local data names are used.
        '''
        phasedict = self.Phases[phasenam] # pointer to current phase info
        Tlist = {}  # histname & T values used for cell w/o Hstrain
        DijTlist = {} # hId & T values used for cell w/Hstrain
        # scan over histograms used in this phase
        for h in phasedict['Histograms']:
            if not phasedict['Histograms'][h]['Use']: continue
            if np.any(abs(np.array(phasedict['Histograms'][h]['HStrain'][0])) > 1e-8):
                DijTlist[h] = self.Histograms[h]['Sample Parameters']['Temperature']
            else:
                Tlist[h] = self.Histograms[h]['Sample Parameters']['Temperature']
        if len(DijTlist) == 0: return
        if len(Tlist) + len(DijTlist) < 2: return
        SGData = phasedict['General']['SGData']
        for i in range(len(G2py3.cellGUIlist)):
            if SGData['SGLaue'] in G2py3.cellGUIlist[i][0]:
                terms = G2py3.cellGUIlist[i][5] + [6]
                break
        else:
            print('ShowHstrainCells error: Laue class not found',SGData['SGLaue'])
            terms = list(range(7))
        
        WriteCIFitem(self.fp, '\n# cell parameters generated by hydrostatic strain')
        WriteCIFitem(self.fp, 'loop_')
        WriteCIFitem(self.fp, '\t _gsas_measurement_temperature')
        for i in terms:
            WriteCIFitem(self.fp, '\t _gsas_cell_'+cellNames[i])
        WriteCIFitem(self.fp, '\t _gsas_cell_histogram_blockid')
        for h,T in Tlist.items():
            pId = phasedict['pId']
            hId = self.Histograms[h]['hId']
            cellList,cellSig = G2stIO.getCellSU(pId,hId,
                                        phasedict['General']['SGData'],
                                        self.parmDict,
                                        self.OverallParms['Covariance'])
            line = '  ' + PutInCol(G2mth.ValEsd(T,-1.),6)
            for i in terms:
                line += PutInCol(G2mth.ValEsd(cellList[i],cellSig[i]),12)
            line += ' ' + datablockidDict[h]
            WriteCIFitem(self.fp, line)
        for h,T in DijTlist.items():
            pId = phasedict['pId']
            hId = self.Histograms[h]['hId']
            cellList,cellSig = G2stIO.getCellSU(pId,hId,
                                        phasedict['General']['SGData'],
                                        self.parmDict,
                                        self.OverallParms['Covariance'])
            line = '  ' + PutInCol(G2mth.ValEsd(T,-1.),6)
            for i in terms:
                line += PutInCol(G2mth.ValEsd(cellList[i],cellSig[i]),12)
            line += ' ' + datablockidDict[h]
            WriteCIFitem(self.fp, line)       

    def _Exporter(self,event=None,phaseOnly=None,histOnly=None):
        '''Basic code to export a CIF. Export can be full or simple, as set by
        phaseOnly and histOnly which skips distances & angles, etc.

        :param bool phaseOnly: used to export only one phase
        :param bool histOnly: used to export only one histogram
        '''

#***** define functions for export method =======================================
        def WriteAudit():
            'Write the CIF audit values. Perhaps should be in a single element loop.'
            WriteCIFitem(self.fp, '_audit_creation_method',
                         'created in GSAS-II')
            WriteCIFitem(self.fp, '_audit_creation_date',self.CIFdate)
            if self.author:
                WriteCIFitem(self.fp, '_audit_author_name',self.author)
            WriteCIFitem(self.fp, '_audit_update_record',
                         self.CIFdate+'  Initial software-generated CIF')

        def WriteOverall(mode=None):
            '''Write out overall refinement information.

            More could be done here, but this is a good start.
            '''
            if self.ifPWDR:
                WriteCIFitem(self.fp, '_pd_proc_info_datetime', self.CIFdate)
                WriteCIFitem(self.fp, '_pd_calc_method', 'Rietveld Refinement')
                
            #WriteCIFitem(self.fp, '_refine_ls_shift/su_mean',DAT2)
            WriteCIFitem(self.fp, '_computing_structure_refinement','GSAS-II (Toby & Von Dreele, J. Appl. Cryst. 46, 544-549, 2013)')
            if self.ifHKLF:
                controls = self.OverallParms['Controls']
                try:
                    if controls['F**2']:
                        thresh = 'F**2>%.1fu(F**2)'%(controls['UsrReject']['minF/sig'])
                    else:
                        thresh = 'F>%.1fu(F)'%(controls['UsrReject']['minF/sig'])
                    WriteCIFitem(self.fp, '_reflns_threshold_expression', thresh)
                except KeyError:
                    pass
            WriteCIFitem(self.fp, '_refine_ls_matrix_type','full')

            if mode == 'seq': return
            try:
                vars = str(len(self.OverallParms['Covariance']['varyList']))
            except:
                vars = '?'
            WriteCIFitem(self.fp, '_refine_ls_number_parameters',vars)
            try:
                GOF = G2mth.ValEsd(self.OverallParms['Covariance']['Rvals']['GOF'],-0.009)
            except:
                GOF = '?'
            WriteCIFitem(self.fp, '_refine_ls_goodness_of_fit_all',GOF)
            DAT1 = self.OverallParms['Covariance']['Rvals'].get('Max shft/sig',0.0)
            if DAT1:
                WriteCIFitem(self.fp, '_refine_ls_shift/su_max','%.4f'%DAT1)

            # get restraint info
            # restraintDict = self.OverallParms.get('Restraints',{})
            # for i in  self.OverallParms['Constraints']:
            #     print i
            #     for j in self.OverallParms['Constraints'][i]:
            #         print j
            #WriteCIFitem(self.fp, '_refine_ls_number_restraints',TEXT)
            # other things to consider reporting
            # _refine_ls_number_reflns
            # _refine_ls_goodness_of_fit_obs
            # _refine_ls_wR_factor_obs
            # _refine_ls_restrained_S_all
            # _refine_ls_restrained_S_obs

            # include an overall profile r-factor, if there is more than one powder histogram
            R = '%.5f'%(self.OverallParms['Covariance']['Rvals']['Rwp']/100.)
            WriteCIFitem(self.fp, '\n# OVERALL WEIGHTED R-FACTOR')
            WriteCIFitem(self.fp, '_refine_ls_wR_factor_obs',R)
                # _refine_ls_R_factor_all
                # _refine_ls_R_factor_obs
            #WriteCIFitem(self.fp, '_refine_ls_matrix_type','userblocks')

        def writeCIFtemplate(G2dict,tmplate,defaultname=''):
            '''Write out the selected or edited CIF template
            An unedited CIF template file is copied, comments intact; an edited
            CIF template is written out from PyCifRW which of course strips comments.
            In all cases the initial data_ header is stripped (there should only be one!)
            '''
            CIFobj = G2dict.get("CIF_template")
            if defaultname:
                defaultname = G2obj.StripUnicode(defaultname)
                defaultname = re.sub(r'[^a-zA-Z0-9_-]','',defaultname)
                defaultname = tmplate + "_" + defaultname + ".cif"
            else:
                defaultname = ''
            templateDefName = 'template_'+tmplate+'.cif'
            if not CIFobj: # copying a template
                for pth in [os.getcwd()]+sys.path:
                    fil = os.path.join(pth,defaultname)
                    if os.path.exists(fil) and defaultname: break
                else:
                    for pth in sys.path:
                        fil = os.path.join(pth,templateDefName)
                        if os.path.exists(fil): break
                    else:
                        print(CIFobj+' not found in path!')
                        return
                fp = open(fil,'r')
                txt = fp.read()
                fp.close()
            elif type(CIFobj) is not list and type(CIFobj) is not tuple:
                if not os.path.exists(CIFobj):
                    print("Error: requested template file has disappeared: "+CIFobj)
                    return
                fp = open(CIFobj,'r')
                txt = fp.read()
                fp.close()
            else:
                txt = dict2CIF(CIFobj[0],CIFobj[1]).WriteOut()
            # remove the PyCifRW header, if present
            #if txt.find('PyCifRW') > -1 and txt.find('data_') > -1:
            txt = "# GSAS-II edited template follows "+txt[txt.index("data_")+5:]
            #txt = txt.replace('data_','#')
            WriteCIFitem(self.fp, txt)

        def FormatSH(phasenam):
            'Format a full spherical harmonics texture description as a string'
            phasedict = self.Phases[phasenam] # pointer to current phase info
            pfx = str(phasedict['pId'])+'::'
            s = ""
            textureData = phasedict['General']['SH Texture']
            if textureData.get('Order'):
                s += "Spherical Harmonics correction. Order = "+str(textureData['Order'])
                s += " Model: " + str(textureData['Model']) + "\n    Orientation angles: "
                for name in ['omega','chi','phi']:
                    aname = pfx+'SH '+name
                    s += name + " = "
                    sig = self.sigDict.get(aname,-0.09)
                    s += G2mth.ValEsd(self.parmDict[aname],sig)
                    s += "; "
                s += "\n"
                s1 = "    Coefficients:  "
                for name in textureData['SH Coeff'][1]:
                    aname = pfx+name
                    if len(s1) > 60:
                        s += s1 + "\n"
                        s1 = "    "
                    s1 += aname + ' = '
                    sig = self.sigDict.get(aname,-0.0009)
                    s1 += G2mth.ValEsd(self.parmDict[aname],sig)
                    s1 += "; "
                s += s1
            return s

        def FormatHAPpo(phasenam):
            '''return the March-Dollase/SH correction for every
            histogram in the current phase formatted into a
            character string
            '''
            phasedict = self.Phases[phasenam] # pointer to current phase info
            s = ''
            for histogram in sorted(phasedict['Histograms']):
                if histogram.startswith("HKLF"): continue # powder only
                if not self.Phases[phasenam]['Histograms'][histogram]['Use']: continue
                Histogram = self.Histograms.get(histogram)
                if not Histogram: continue
                hapData = phasedict['Histograms'][histogram]
                if hapData['Pref.Ori.'][0] == 'MD':
                    aname = str(phasedict['pId'])+':'+str(Histogram['hId'])+':MD'
                    if self.parmDict.get(aname,1.0) != 1.0: continue
                    sig = self.sigDict.get(aname,-0.009)
                    if s != "": s += '\n'
                    s += 'March-Dollase correction'
                    if len(self.powderDict) > 1:
                        s += ', histogram '+str(Histogram['hId']+1)
                    s += ' coef. = ' + G2mth.ValEsd(self.parmDict[aname],sig)
                    s += ' axis = ' + str(hapData['Pref.Ori.'][3])
                else: # must be SH
                    if s != "": s += '\n'
                    s += 'Simple spherical harmonic correction'
                    if len(self.powderDict) > 1:
                        s += ', histogram '+str(Histogram['hId']+1)
                    s += ' Order = '+str(hapData['Pref.Ori.'][4])+'\n'
                    s1 = "    Coefficients:  "
                    for item in hapData['Pref.Ori.'][5]:
                        aname = str(phasedict['pId'])+':'+str(Histogram['hId'])+':'+item
                        if len(s1) > 60:
                            s += s1 + "\n"
                            s1 = "    "
                        s1 += aname + ' = '
                        sig = self.sigDict.get(aname,-0.0009)
                        s1 += G2mth.ValEsd(self.parmDict[aname],sig)
                        s1 += "; "
                    s += s1
            return s

        def FormatBackground(bkg,hId):
            '''Display the Background information as a descriptive text string.

            TODO: this needs to be expanded to show the diffuse peak and
            Debye term information as well. (Bob)

            :returns: the text description (str)
            '''
            hfx = ':'+str(hId)+':'
            fxn, bkgdict = bkg
            terms = fxn[2]
            txt = 'Background function: "'+fxn[0]+'" function with '+str(terms)+' terms:\n'
            l = "    "
            for i,v in enumerate(fxn[3:]):
                name = '%sBack;%d'%(hfx,i)
                sig = self.sigDict.get(name,-0.009)
                if len(l) > 60:
                    txt += l + '\n'
                    l = '    '
                l += G2mth.ValEsd(v,sig)+', '
            txt += l
            if bkgdict['nDebye']:
                txt += '\n  Background Debye function parameters: A, R, U:'
                names = ['A;','R;','U;']
                for i in range(bkgdict['nDebye']):
                    txt += '\n    '
                    for j in range(3):
                        name = hfx+'Debye'+names[j]+str(i)
                        sig = self.sigDict.get(name,-0.009)
                        txt += G2mth.ValEsd(bkgdict['debyeTerms'][i][2*j],sig)+', '
            if bkgdict['nPeaks']:
                txt += '\n  Background peak parameters: pos, int, sig, gam:'
                names = ['pos;','int;','sig;','gam;']
                for i in range(bkgdict['nPeaks']):
                    txt += '\n    '
                    for j in range(4):
                        name = hfx+'BkPk'+names[j]+str(i)
                        sig = self.sigDict.get(name,-0.009)
                        txt += G2mth.ValEsd(bkgdict['peaksList'][i][2*j],sig)+', '
            return txt

        def FormatInstProfile(instparmdict,hId):
            '''Format the instrumental profile parameters with a
            string description. Will only be called on PWDR histograms
            '''
            s = ''
            inst = instparmdict[0]
            hfx = ':'+str(hId)+':'
            if 'C' in inst['Type'][0]:
                s = 'Finger-Cox-Jephcoat function parameters U, V, W, X, Y, SH/L:\n'
                s += '  peak variance(Gauss) = Utan(Th)^2^+Vtan(Th)+W:\n'
                s += '  peak HW(Lorentz) = X/cos(Th)+Ytan(Th); SH/L = S/L+H/L\n'
                s += '  U, V, W in (centideg)^2^, X & Y in centideg\n    '
                for item in ['U','V','W','X','Y','SH/L']:
                    name = hfx+item
                    sig = self.sigDict.get(name,-0.009)
                    s += G2mth.ValEsd(inst[item][1],sig)+', '
            elif 'T' in inst['Type'][0]:    #to be tested after TOF Rietveld done
                s = 'Von Dreele-Jorgenson-Windsor function parameters\n'+ \
                    '   alpha, beta-0, beta-1, beta-q, sig-0, sig-1, sig-2, sig-q, X, Y:\n    '
                for item in ['alpha','beta-0','beta-1','beta-q','sig-0','sig-1','sig-2','sig-q','X','Y']:
                    name = hfx+item
                    sig = self.sigDict.get(name,-0.009)
                    s += G2mth.ValEsd(inst[item][1],sig)+', '
            return s

        def FormatPhaseProfile(phasenam,hist=''):
            '''Format the phase-related profile parameters (size/strain)
            with a string description.
            return an empty string or None if there are no
            powder histograms for this phase.
            '''
            s = ''
            phasedict = self.Phases[phasenam] # pointer to current phase info
            if hist:
                parmDict = self.seqData[hist]['parmDict']
                sigDict = dict(zip(self.seqData[hist]['varyList'],self.seqData[hist]['sig']))
            else:
                parmDict = self.parmDict
                sigDict = self.sigDict
            
            SGData = phasedict['General'] ['SGData']
            for histogram in sorted(phasedict['Histograms']):
                if hist is not None and hist != histogram: continue
                if histogram.startswith("HKLF"): continue # powder only
                Histogram = self.Histograms.get(histogram)
                if not Histogram: continue
                hapData = phasedict['Histograms'][histogram]
                pId = phasedict['pId']
                hId = Histogram['hId']
                phfx = '%d:%d:'%(pId,hId)
                size = hapData['Size']
                mustrain = hapData['Mustrain']
                hstrain = hapData['HStrain']
                if s: s += '\n'
                if len(self.powderDict) > 1: # if one histogram, no ambiguity
                    s += '  Parameters for histogram #{:} {:} & phase {:}\n'.format(
                        str(hId),str(histogram),phasenam)
                s += '  Crystallite size in microns with "%s" model:\n  '%(size[0])
                names = ['Size;i','Size;mx']
                if 'uniax' in size[0]:
                    names = ['Size;i','Size;a','Size;mx']
                    s += 'anisotropic axis is %s\n  '%(str(size[3]))
                    s += 'parameters: equatorial size, axial size, G/L mix\n    '
                    for i,item in enumerate(names):
                        name = phfx+item
                        val = parmDict.get(name,size[1][i])
                        sig = sigDict.get(name,-0.009)
                        s += G2mth.ValEsd(val,sig)+', '
                elif 'ellip' in size[0]:
                    s += 'parameters: S11, S22, S33, S12, S13, S23, G/L mix\n    '
                    for i in range(6):
                        name = phfx+'Size:'+str(i)
                        val = parmDict.get(name,size[4][i])
                        sig = sigDict.get(name,-0.009)
                        s += G2mth.ValEsd(val,sig)+', '
                    sig = sigDict.get(phfx+'Size;mx',-0.009)
                    s += G2mth.ValEsd(size[1][2],sig)+', '
                else:       #isotropic
                    s += 'parameters: Size, G/L mix\n    '
                    i = 0
                    for item in names:
                        name = phfx+item
                        val = parmDict.get(name,size[1][i])
                        sig = sigDict.get(name,-0.009)
                        s += G2mth.ValEsd(val,sig)+', '
                        i = 2    #skip the aniso value
                s += '\n  Microstrain, "%s" model (10^6^ * delta Q/Q)\n  '%(mustrain[0])
                names = ['Mustrain;i','Mustrain;mx']
                if 'uniax' in mustrain[0]:
                    names = ['Mustrain;i','Mustrain;a','Mustrain;mx']
                    s += 'anisotropic axis is %s\n  '%(str(size[3]))
                    s += 'parameters: equatorial mustrain, axial mustrain, G/L mix\n    '
                    for i,item in enumerate(names):
                        name = phfx+item
                        val = parmDict.get(name,mustrain[1][i])
                        sig = sigDict.get(name,-0.009)
                        s += G2mth.ValEsd(val,sig)+', '
                elif 'general' in mustrain[0]:
                    names = 'parameters: '
                    for i,name in enumerate(G2spc.MustrainNames(SGData)):
                        names += name+', '
                        if i == 9:
                            names += '\n  '
                    names += 'G/L mix\n    '
                    s += names
                    txt = ''
                    for i in range(len(mustrain[4])):
                        name = phfx+'Mustrain:'+str(i)
                        val = parmDict.get(name,mustrain[4][i])
                        sig = sigDict.get(name,-0.009)
                        if len(txt) > 60:
                            s += txt+'\n    '
                            txt = ''
                        txt += G2mth.ValEsd(val,sig)+', '
                    s += txt
                    name = phfx+'Mustrain;mx'
                    val = parmDict.get(name,mustrain[1][2])
                    sig = sigDict.get(name,-0.009)
                    s += G2mth.ValEsd(val,sig)+', '

                else:       #isotropic
                    s += '  parameters: Mustrain, G/L mix\n    '
                    i = 0
                    for item in names:
                        name = phfx+item
                        val = parmDict.get(name,mustrain[1][i])
                        sig = sigDict.get(name,-0.009)
                        s += G2mth.ValEsd(val,sig)+', '
                        i = 2    #skip the aniso value
                s1 = '  \n  Macrostrain parameters: '
                names = G2spc.HStrainNames(SGData)
                for name in names:
                    s1 += name+', '
                s1 += '\n    '
                macrostrain = False
                for i in range(len(names)):
                    name = phfx+names[i]
                    val = parmDict.get(name,hstrain[0][i])
                    sig = sigDict.get(name,-0.000009)
                    s1 += G2mth.ValEsd(val,sig)+', '
                    if hstrain[0][i]: macrostrain = True
                if macrostrain:
                    s += s1 + '\n'
                    # show revised lattice parameters here someday
                else:
                    s += '\n'
            return s

        def MakeUniqueLabel(lbl,labellist):
            'Make sure that every atom label is unique'
            lbl = lbl.strip()
            if not lbl: # deal with a blank label
                lbl = 'A_1'
            if lbl not in labellist:
                labellist.append(lbl)
                return lbl
            i = 1
            prefix = lbl
            if '_' in lbl:
                prefix = lbl[:lbl.rfind('_')]
                suffix = lbl[lbl.rfind('_')+1:]
                try:
                    i = int(suffix)+1
                except:
                    pass
            while prefix+'_'+str(i) in labellist:
                i += 1
            else:
                lbl = prefix+'_'+str(i)
                labellist.append(lbl)

        def WriteDistances(phasenam):
            '''Report bond distances and angles for the CIF

            Note that _geom_*_symmetry_* fields are values of form
            n_klm where n is the symmetry operation in SymOpList (counted
            starting with 1) and (k-5, l-5, m-5) are translations to add
            to (x,y,z). See
            http://www.iucr.org/__data/iucr/cifdic_html/1/cif_core.dic/Igeom_angle_site_symmetry_.html

            TODO: need a method to select publication flags for distances/angles
            '''
            phasedict = self.Phases[phasenam] # pointer to current phase info
            Atoms = phasedict['Atoms']
            generalData = phasedict['General']
            # create a dict for storing Pub flag for bonds/angles, if needed
            if phasedict['General'].get("DisAglHideFlag") is None:
                phasedict['General']["DisAglHideFlag"] = {}
            DisAngSel = phasedict['General']["DisAglHideFlag"]
            cx,ct,cs,cia = phasedict['General']['AtomPtrs']
            cn = ct-1
            fpfx = str(phasedict['pId'])+'::Afrac:'
            cfrac = cx+3
            DisAglData = {}
            # create a list of atoms, but skip atoms with zero occupancy
            xyz = []
            fpfx = str(phasedict['pId'])+'::Afrac:'
            for i,atom in enumerate(Atoms):
                if self.parmDict.get(fpfx+str(i),atom[cfrac]) == 0.0: continue
                xyz.append([i,]+atom[cn:cn+2]+atom[cx:cx+3])
            if 'DisAglCtls' not in generalData:
                # should not happen, since DisAglDialog should be called
                # for all phases before getting here
                dlg = G2G.DisAglDialog(
                    self.G2frame,
                    {},
                    generalData)
                if dlg.ShowModal() == wx.ID_OK:
                    generalData['DisAglCtls'] = dlg.GetData()
                else:
                    dlg.Destroy()
                    return
                dlg.Destroy()
            DisAglData['OrigAtoms'] = xyz
            DisAglData['TargAtoms'] = xyz
            SymOpList,offsetList,symOpList,G2oprList,G2opcodes = G2spc.AllOps(
                generalData['SGData'])

#            xpandSGdata = generalData['SGData'].copy()
#            xpandSGdata.update({'SGOps':symOpList,
#                                'SGInv':False,
#                                'SGLatt':'P',
#                                'SGCen':np.array([[0, 0, 0]]),})
#            DisAglData['SGData'] = xpandSGdata
            DisAglData['SGData'] = generalData['SGData'].copy()

            DisAglData['Cell'] = generalData['Cell'][1:] #+ volume
            if 'pId' in phasedict:
                DisAglData['pId'] = phasedict['pId']
                DisAglData['covData'] = self.OverallParms['Covariance']
            try:
                AtomLabels,DistArray,AngArray = G2stMn.RetDistAngle(
                    generalData['DisAglCtls'],
                    DisAglData)
            except KeyError:        # inside DistAngle for missing atom types in DisAglCtls
                print(u'**** ERROR computing distances & angles for phase {} ****\nresetting to default values'.format(phasenam))
                data = generalData['DisAglCtls'] = {}
                data['Name'] = generalData['Name']
                data['Factors'] = [0.85,0.85]
                data['AtomTypes'] = generalData['AtomTypes']
                data['BondRadii'] = generalData['BondRadii'][:]
                data['AngleRadii'] = generalData['AngleRadii'][:]
                try:
                    AtomLabels,DistArray,AngArray = G2stMn.RetDistAngle(
                        generalData['DisAglCtls'],
                        DisAglData)
                except:
                    print('Reset failed. To fix this, use the Reset button in the "edit distance/angle menu" for this phase')
                    return

            # loop over interatomic distances for this phase
            WriteCIFitem(self.fp, '\n# MOLECULAR GEOMETRY')
            First = True
            for i in sorted(AtomLabels.keys()):
                Dist = DistArray[i]
                for D in Dist:
                    line = '  '+PutInCol(AtomLabels[i],6)+PutInCol(AtomLabels[D[0]],6)
                    sig = D[4]
                    if sig == 0: sig = -0.00009
                    line += PutInCol(G2mth.ValEsd(D[3],sig,True),10)
                    line += "  1_555 "
                    symopNum = G2opcodes.index(D[2])
                    line += " {:3d}_".format(symopNum+1)
                    for d,o in zip(D[1],offsetList[symopNum]):
                        line += "{:1d}".format(d-o+5)
                    if DisAngSel.get((i,tuple(D[0:3]))):
                        line += " no"
                    else:
                        line += " yes"
                    if First:
                        First = False
                        WriteCIFitem(self.fp, 'loop_' +
                         '\n   _geom_bond_atom_site_label_1' +
                         '\n   _geom_bond_atom_site_label_2' +
                         '\n   _geom_bond_distance' +
                         '\n   _geom_bond_site_symmetry_1' +
                         '\n   _geom_bond_site_symmetry_2' +
                         '\n   _geom_bond_publ_flag')
                    WriteCIFitem(self.fp, line)

            # loop over interatomic angles for this phase
            First = True
            for i in sorted(AtomLabels.keys()):
                Dist = DistArray[i]
                for k,j,tup in AngArray[i]:
                    Dj = Dist[j]
                    Dk = Dist[k]
                    line = '  '+PutInCol(AtomLabels[Dj[0]],6)+PutInCol(AtomLabels[i],6)+PutInCol(AtomLabels[Dk[0]],6)
                    sig = tup[1]
                    if sig == 0: sig = -0.009
                    line += PutInCol(G2mth.ValEsd(tup[0],sig,True),10)
                    line += " {:3d}_".format(G2opcodes.index(Dj[2])+1)
                    for d in Dj[1]:
                        line += "{:1d}".format(d+5)
                    line += "  1_555 "
                    line += " {:3d}_".format(G2opcodes.index(Dk[2])+1)
                    for d in Dk[1]:
                        line += "{:1d}".format(d+5)
                    key = (tuple(Dk[0:3]),i,tuple(Dj[0:3]))
                    if DisAngSel.get(key):
                        line += " no"
                    else:
                        line += " yes"
                    if First:
                        First = False
                        WriteCIFitem(self.fp, '\nloop_' +
                         '\n   _geom_angle_atom_site_label_1' +
                         '\n   _geom_angle_atom_site_label_2' +
                         '\n   _geom_angle_atom_site_label_3' +
                         '\n   _geom_angle' +
                         '\n   _geom_angle_site_symmetry_1' +
                         '\n   _geom_angle_site_symmetry_2' +
                         '\n   _geom_angle_site_symmetry_3' +
                         '\n   _geom_angle_publ_flag')
                    WriteCIFitem(self.fp, line)


        def WriteSeqDistances(phasenam,histname,phasedict,cellList,seqData):
            '''Report bond distances and angles for the CIF from a Sequential fit

            Note that _geom_*_symmetry_* fields are values of form
            n_klm where n is the symmetry operation in SymOpList (counted
            starting with 1) and (k-5, l-5, m-5) are translations to add
            to (x,y,z). See
            http://www.iucr.org/__data/iucr/cifdic_html/1/cif_core.dic/Igeom_angle_site_symmetry_.html

            TODO: this is based on WriteDistances and could likely be merged with that
            without too much work.

            TODO: need a method to select publication flags for distances/angles
            '''
            #breakpoint()
            Atoms = phasedict['Atoms']
            generalData = phasedict['General']
            parmDict = seqData[histname]['parmDict']
#            sigDict = dict(zip(seqData[hist]['varyList'],seqData[hist]['sig']))
            # create a dict for storing Pub flag for bonds/angles, if needed
            if phasedict['General'].get("DisAglHideFlag") is None:
                phasedict['General']["DisAglHideFlag"] = {}
            DisAngSel = phasedict['General']["DisAglHideFlag"]
            cx,ct,cs,cia = phasedict['General']['AtomPtrs']
            cn = ct-1
#            fpfx = str(phasedict['pId'])+'::Afrac:'
            cfrac = cx+3
            DisAglData = {}
            # create a list of atoms, but skip atoms with zero occupancy
            xyz = []
            fpfx = str(phasedict['pId'])+'::Afrac:'
            for i,atom in enumerate(Atoms):
                if parmDict.get(fpfx+str(i),atom[cfrac]) == 0.0: continue
                thisatom = [i] + atom[cn:cn+2]
                for j,lab in enumerate(['x','y','z']):
                    xyzkey = str(phasedict['pId'])+'::A'+ lab + ':' +str(i)
                    thisatom.append(parmDict.get(xyzkey,atom[cx+j]))
                xyz.append(thisatom)
            DisAglData['OrigAtoms'] = xyz
            DisAglData['TargAtoms'] = xyz
            SymOpList,offsetList,symOpList,G2oprList,G2opcodes = G2spc.AllOps(
                generalData['SGData'])

#            xpandSGdata = generalData['SGData'].copy()
#            xpandSGdata.update({'SGOps':symOpList,
#                                'SGInv':False,
#                                'SGLatt':'P',
#                                'SGCen':np.array([[0, 0, 0]]),})
#            DisAglData['SGData'] = xpandSGdata
            DisAglData['SGData'] = generalData['SGData'].copy()

            DisAglData['Cell'] = cellList  #+ volume
            if 'pId' in phasedict:
                DisAglData['pId'] = phasedict['pId']
                DisAglData['covData'] = seqData[histname]
                # self.OverallParms['Covariance']
            try:
                AtomLabels,DistArray,AngArray = G2stMn.RetDistAngle(
                    generalData['DisAglCtls'],
                    DisAglData)
            except KeyError:        # inside DistAngle for missing atom types in DisAglCtls
                print(u'**** ERROR computing distances & angles for phase {} ****\nresetting to default values'.format(phasenam))
                data = generalData['DisAglCtls'] = {}
                data['Name'] = generalData['Name']
                data['Factors'] = [0.85,0.85]
                data['AtomTypes'] = generalData['AtomTypes']
                data['BondRadii'] = generalData['BondRadii'][:]
                data['AngleRadii'] = generalData['AngleRadii'][:]
                try:
                    AtomLabels,DistArray,AngArray = G2stMn.RetDistAngle(
                        generalData['DisAglCtls'],
                        DisAglData)
                except:
                    print('Reset failed. To fix this, use the Reset button in the "edit distance/angle menu" for this phase')
                    return

            # loop over interatomic distances for this phase
            WriteCIFitem(self.fp, '\n# MOLECULAR GEOMETRY')
            First = True
            for i in sorted(AtomLabels.keys()):
                Dist = DistArray[i]
                for D in Dist:
                    line = '  '+PutInCol(AtomLabels[i],6)+PutInCol(AtomLabels[D[0]],6)
                    sig = D[4]
                    if sig == 0: sig = -0.00009
                    line += PutInCol(G2mth.ValEsd(D[3],sig,True),10)
                    line += "  1_555 "
                    symopNum = G2opcodes.index(D[2])
                    line += " {:3d}_".format(symopNum+1)
                    for d,o in zip(D[1],offsetList[symopNum]):
                        line += "{:1d}".format(d-o+5)
                    if DisAngSel.get((i,tuple(D[0:3]))):
                        line += " no"
                    else:
                        line += " yes"
                    if First:
                        First = False
                        WriteCIFitem(self.fp, 'loop_' +
                         '\n   _geom_bond_atom_site_label_1' +
                         '\n   _geom_bond_atom_site_label_2' +
                         '\n   _geom_bond_distance' +
                         '\n   _geom_bond_site_symmetry_1' +
                         '\n   _geom_bond_site_symmetry_2' +
                         '\n   _geom_bond_publ_flag')
                    WriteCIFitem(self.fp, line)

            # loop over interatomic angles for this phase
            First = True
            for i in sorted(AtomLabels.keys()):
                Dist = DistArray[i]
                for k,j,tup in AngArray[i]:
                    Dj = Dist[j]
                    Dk = Dist[k]
                    line = '  '+PutInCol(AtomLabels[Dj[0]],6)+PutInCol(AtomLabels[i],6)+PutInCol(AtomLabels[Dk[0]],6)
                    sig = tup[1]
                    if sig == 0: sig = -0.009
                    line += PutInCol(G2mth.ValEsd(tup[0],sig,True),10)
                    line += " {:3d}_".format(G2opcodes.index(Dj[2])+1)
                    for d in Dj[1]:
                        line += "{:1d}".format(d+5)
                    line += "  1_555 "
                    line += " {:3d}_".format(G2opcodes.index(Dk[2])+1)
                    for d in Dk[1]:
                        line += "{:1d}".format(d+5)
                    key = (tuple(Dk[0:3]),i,tuple(Dj[0:3]))
                    if DisAngSel.get(key):
                        line += " no"
                    else:
                        line += " yes"
                    if First:
                        First = False
                        WriteCIFitem(self.fp, '\nloop_' +
                         '\n   _geom_angle_atom_site_label_1' +
                         '\n   _geom_angle_atom_site_label_2' +
                         '\n   _geom_angle_atom_site_label_3' +
                         '\n   _geom_angle' +
                         '\n   _geom_angle_site_symmetry_1' +
                         '\n   _geom_angle_site_symmetry_2' +
                         '\n   _geom_angle_site_symmetry_3' +
                         '\n   _geom_angle_publ_flag')
                    WriteCIFitem(self.fp, line)

        def WriteSeqOverallPhaseInfo(phasenam,histblk):
            'Write out the phase information for the selected phase for the overall block in a sequential fit'
            WriteCIFitem(self.fp, '# overall phase info for '+str(phasenam) + ' follows')
            phasedict = self.Phases[phasenam] # pointer to current phase info
            WriteCIFitem(self.fp, '_pd_phase_name', phasenam)

            WriteCIFitem(self.fp, '_symmetry_cell_setting',
                         phasedict['General']['SGData']['SGSys'])

            if phasedict['General']['Type'] in ['nuclear','macromolecular']:
                spacegroup = phasedict['General']['SGData']['SpGrp'].strip()
                # regularize capitalization and remove trailing H/R
                spacegroup = spacegroup[0].upper() + spacegroup[1:].lower().rstrip('rh ')
                WriteCIFitem(self.fp, '_symmetry_space_group_name_H-M',spacegroup)
    
                # generate symmetry operations including centering and center of symmetry
                SymOpList,offsetList,symOpList,G2oprList,G2opcodes = G2spc.AllOps(
                    phasedict['General']['SGData'])
                WriteCIFitem(self.fp, 'loop_\n    _space_group_symop_id\n    _space_group_symop_operation_xyz')
                for i,op in enumerate(SymOpList,start=1):
                    WriteCIFitem(self.fp, '   {:3d}  {:}'.format(i,op.lower()))
            elif phasedict['General']['Type'] == 'magnetic':
                parentSpGrp = phasedict['General']['SGData']['SpGrp'].strip()
                parentSpGrp = parentSpGrp[0].upper() + parentSpGrp[1:].lower().rstrip('rh ')
                WriteCIFitem(self.fp, '_parent_space_group.name_H-M_alt',parentSpGrp)
#                [Trans,Uvec,Vvec] = phasedict['General']['SGData']['fromParent']         #save these
                spacegroup = phasedict['General']['SGData']['MagSpGrp'].strip()
                spacegroup = spacegroup[0].upper() + spacegroup[1:].lower().rstrip('rh ')
                WriteCIFitem(self.fp, '_space_group_magn.name_BNS',spacegroup)
                WriteCIFitem(self.fp, '_space_group.magn_point_group',phasedict['General']['SGData']['MagPtGp'])

                # generate symmetry operations including centering and center of symmetry
                SymOpList,offsetList,symOpList,G2oprList,G2opcodes = G2spc.AllOps(
                    phasedict['General']['SGData'])
                SpnFlp = phasedict['General']['SGData']['SpnFlp']
                WriteCIFitem(self.fp, 'loop_\n    _space_group_symop_magn_operation.id\n    _space_group_symop_magn_operation.xyz')
                for i,op in enumerate(SymOpList,start=1):
                    if SpnFlp[i-1] >0:
                        opr = op.lower()+',+1'
                    else:
                        opr = op.lower()+',-1'
                    WriteCIFitem(self.fp, '   {:3d}  {:}'.format(i,opr))
                    
            lam = None
            if 'X' in histblk['Instrument Parameters'][0]['Type'][0]:
                for k in ('Lam','Lam1'):
                    if k in histblk['Instrument Parameters'][0]:
                        lam = histblk['Instrument Parameters'][0][k][0]
                        break
            keV = None
            if lam: keV = 12.397639/lam
            # report cell contents                        
            WriteComposition(self.fp, self.Phases[phasenam], phasenam, self.parmDict, False, keV)
        
        def WriteSeqPhaseVals(phasenam,phasedict,pId,histname):
            'Write out the phase information for the selected phase'
            WriteCIFitem(self.fp, '_pd_phase_name', phasenam)
            cellList,cellSig = getCellwStrain(phasedict,self.seqData,pId,histname)
            T = self.Histograms[histname]['Sample Parameters']['Temperature']
            try:
                T = G2mth.ValEsd(T,-1.0)
            except:
                pass
            WriteCIFitem(self.fp, '_symmetry_cell_setting',
                         phasedict['General']['SGData']['SGSys'])

            if phasedict['General']['Type'] in ['nuclear','macromolecular']:
                spacegroup = phasedict['General']['SGData']['SpGrp'].strip()
                # regularize capitalization and remove trailing H/R
                spacegroup = spacegroup[0].upper() + spacegroup[1:].lower().rstrip('rh ')
                WriteCIFitem(self.fp, '_symmetry_space_group_name_H-M',spacegroup)
            WriteCIFitem(self.fp,"_cell_measurement_temperature",T)
            defsigL = 3*[-0.00001] + 3*[-0.001] + [-0.01] # significance to use when no sigma
            prevsig = 0
            for lbl,defsig,val,sig in zip(cellNames,defsigL,cellList,cellSig):
                if sig:
                    txt = G2mth.ValEsd(val,sig)
                    prevsig = -sig # use this as the significance for next value
                else:
                    txt = G2mth.ValEsd(val,min(defsig,prevsig),True)
                WriteCIFitem(self.fp, '_cell_'+lbl,txt)

            mass = G2mth.getMass(phasedict['General'])
            Volume = cellList[6]
            density = mass/(0.6022137*Volume)
            WriteCIFitem(self.fp, '_exptl_crystal_density_diffrn',
                    G2mth.ValEsd(density,-0.001))

            # report atom params
            if phasedict['General']['Type'] in ['nuclear','macromolecular']:        #this needs macromolecular variant, etc!
                WriteSeqAtomsNuclear(self.fp, cellList, phasedict, phasenam, histname, 
                                         self.seqData, self.OverallParms['Rigid bodies'])
            else:
                print("Warning: no export for sequential "+str(phasedict['General']['Type'])+" coordinates implemented")
#                raise Exception("no export for "+str(phasedict['General']['Type'])+" coordinates implemented")

            if phasedict['General']['Type'] == 'nuclear':
                WriteSeqDistances(phasenam,histname,phasedict,cellList,self.seqData)

            # N.B. map info probably not possible w/sequential
#            if 'Map' in phasedict['General'] and 'minmax' in phasedict['General']['Map']:
#                WriteCIFitem(self.fp, '\n# Difference density results')
#                MinMax = phasedict['General']['Map']['minmax']
#                WriteCIFitem(self.fp, '_refine_diff_density_max',G2mth.ValEsd(MinMax[0],-0.009))
#                WriteCIFitem(self.fp, '_refine_diff_density_min',G2mth.ValEsd(MinMax[1],-0.009))
                
        def WritePhaseInfo(phasenam,quick=True,oneblock=True):
            'Write out the phase information for the selected phase'
            WriteCIFitem(self.fp, '\n# phase info for '+str(phasenam) + ' follows')
            phasedict = self.Phases[phasenam] # pointer to current phase info
            WriteCIFitem(self.fp, '_pd_phase_name', phasenam)
            cellList,cellSig = self.GetCell(phasenam)
            if quick:  # leave temperature as unknown
                WriteCIFitem(self.fp,"_cell_measurement_temperature","?")
            elif oneblock:
                pass # temperature should be written when the histogram saved later
            else: # get T set in _SelectPhaseT_CellSelectHist and possibly get new cell params
                T,hRanId = self.CellHistSelection.get(phasedict['ranId'],
                                                          ('?',None))
                try:
                    T = G2mth.ValEsd(T,-1.0)
                except:
                    pass
                WriteCIFitem(self.fp,"_cell_measurement_temperature",T)
                for h in self.Histograms:
                    if self.Histograms[h]['ranId'] == hRanId:
                        pId = phasedict['pId']
                        hId = self.Histograms[h]['hId']
                        cellList,cellSig = G2stIO.getCellSU(pId,hId,
                                        phasedict['General']['SGData'],
                                        self.parmDict,
                                        self.OverallParms['Covariance'])
                        break
                else:
                    T = '?'

            defsigL = 3*[-0.00001] + 3*[-0.001] + [-0.01] # significance to use when no sigma
            prevsig = 0
            for lbl,defsig,val,sig in zip(cellNames,defsigL,cellList,cellSig):
                if sig:
                    txt = G2mth.ValEsd(val,sig)
                    prevsig = -sig # use this as the significance for next value
                else:
                    txt = G2mth.ValEsd(val,min(defsig,prevsig),True)
                WriteCIFitem(self.fp, '_cell_'+lbl,txt)
                
            density = G2mth.getDensity(phasedict['General'])[0]
            WriteCIFitem(self.fp, '_exptl_crystal_density_diffrn',
                    G2mth.ValEsd(density,-0.001))                    

            WriteCIFitem(self.fp, '_symmetry_cell_setting',
                         phasedict['General']['SGData']['SGSys'])

            if phasedict['General']['Type'] in ['nuclear','macromolecular']:
                spacegroup = phasedict['General']['SGData']['SpGrp'].strip()
                # regularize capitalization and remove trailing H/R
                spacegroup = spacegroup[0].upper() + spacegroup[1:].lower().rstrip('rh ')
                WriteCIFitem(self.fp, '_symmetry_space_group_name_H-M',spacegroup)
    
                # generate symmetry operations including centering and center of symmetry
                SymOpList,offsetList,symOpList,G2oprList,G2opcodes = G2spc.AllOps(
                    phasedict['General']['SGData'])
                WriteCIFitem(self.fp, 'loop_\n    _space_group_symop_id\n    _space_group_symop_operation_xyz')
                for i,op in enumerate(SymOpList,start=1):
                    WriteCIFitem(self.fp, '   {:3d}  {:}'.format(i,op.lower()))
            elif phasedict['General']['Type'] == 'magnetic':
                parentSpGrp = phasedict['General']['SGData']['SpGrp'].strip()
                parentSpGrp = parentSpGrp[0].upper() + parentSpGrp[1:].lower().rstrip('rh ')
                WriteCIFitem(self.fp, '_parent_space_group.name_H-M_alt',parentSpGrp)
#                [Trans,Uvec,Vvec] = phasedict['General']['SGData']['fromParent']         #save these
                spacegroup = phasedict['General']['SGData']['MagSpGrp'].strip()
                spacegroup = spacegroup[0].upper() + spacegroup[1:].lower().rstrip('rh ')
                WriteCIFitem(self.fp, '_space_group_magn.name_BNS',spacegroup)
                WriteCIFitem(self.fp, '_space_group.magn_point_group',phasedict['General']['SGData']['MagPtGp'])

                # generate symmetry operations including centering and center of symmetry
                SymOpList,offsetList,symOpList,G2oprList,G2opcodes = G2spc.AllOps(
                    phasedict['General']['SGData'])
                SpnFlp = phasedict['General']['SGData']['SpnFlp']
                WriteCIFitem(self.fp, 'loop_\n    _space_group_symop_magn_operation.id\n    _space_group_symop_magn_operation.xyz')
                for i,op in enumerate(SymOpList,start=1):
                    if SpnFlp[i-1] >0:
                        opr = op.lower()+',+1'
                    else:
                        opr = op.lower()+',-1'
                    WriteCIFitem(self.fp, '   {:3d}  {:}'.format(i,opr))

            # loop over histogram(s) used in this phase
            if not oneblock and not self.quickmode:
                # report pointers to the histograms used in this phase
                histlist = []
                for hist in self.Phases[phasenam]['Histograms']:
                    if self.Phases[phasenam]['Histograms'][hist]['Use']:
                        if phasebyhistDict.get(hist):
                            phasebyhistDict[hist].append(phasenam)
                        else:
                            phasebyhistDict[hist] = [phasenam,]
                        blockid = datablockidDict.get(hist)
                        if not blockid:
                            print("Internal error: no block for data. Phase "+str(
                                phasenam)+" histogram "+str(hist))
                            histlist = []
                            break
                        histlist.append(blockid)

                if len(histlist) == 0:
                    WriteCIFitem(self.fp, '# Note: phase has no associated data')

            # report atom params
            if phasedict['General']['Type'] in ['nuclear','macromolecular']:        #this needs macromolecular variant, etc!
                try:
                    self.labellist
                except AttributeError:
                    self.labellist = []
                WriteAtomsNuclear(self.fp, self.Phases[phasenam], phasenam,
                                  self.parmDict, self.sigDict, self.labellist,
                                      self.OverallParms['Rigid bodies'])
            else:
                try:
                    self.labellist
                except AttributeError:
                    self.labellist = []
                WriteAtomsMagnetic(self.fp, self.Phases[phasenam], phasenam,
                                  self.parmDict, self.sigDict, self.labellist)
#                raise Exception("no export for "+str(phasedict['General']['Type'])+" coordinates implemented")
            keV = None             
            if oneblock: # get xray wavelength
                lamlist = []
                for hist in self.Histograms:
                    if 'X' not in self.Histograms[hist]['Instrument Parameters'][0]['Type'][0]:
                        continue
                    for k in ('Lam','Lam1'):
                        if k in self.Histograms[hist]['Instrument Parameters'][0]:
                            lamlist.append(self.Histograms[hist]['Instrument Parameters'][0][k][0])
                            break
                if len(lamlist) == 1:
                    keV = 12.397639/lamlist[0]

            # report cell contents                        
            WriteComposition(self.fp, self.Phases[phasenam], phasenam, self.parmDict, self.quickmode, keV)
            if not self.quickmode and phasedict['General']['Type'] == 'nuclear':      # report distances and angles
                WriteDistances(phasenam)
            if 'Map' in phasedict['General'] and 'minmax' in phasedict['General']['Map']:
                WriteCIFitem(self.fp, '\n# Difference density results')
                MinMax = phasedict['General']['Map']['minmax']
                WriteCIFitem(self.fp, '_refine_diff_density_max',G2mth.ValEsd(MinMax[0],-0.009))
                WriteCIFitem(self.fp, '_refine_diff_density_min',G2mth.ValEsd(MinMax[1],-0.009))
                
        def Yfmt(ndec,val):
            'Format intensity values'
            try:
                out = ("{:."+str(ndec)+"f}").format(val)
                out = out.rstrip('0')  # strip zeros to right of decimal
                return out.rstrip('.')  # and decimal place when not needed
            except TypeError:
                print(val)
                return '.'
            
        def WriteReflStat(refcount,hklmin,hklmax,dmin,dmax,nRefSets=1):
            'Write reflection statistics'
            WriteCIFitem(self.fp, '_reflns_number_total', str(refcount))
            if hklmin is not None and nRefSets == 1: # hkl range has no meaning with multiple phases
                WriteCIFitem(self.fp, '_reflns_limit_h_min', str(int(hklmin[0])))
                WriteCIFitem(self.fp, '_reflns_limit_h_max', str(int(hklmax[0])))
                WriteCIFitem(self.fp, '_reflns_limit_k_min', str(int(hklmin[1])))
                WriteCIFitem(self.fp, '_reflns_limit_k_max', str(int(hklmax[1])))
                WriteCIFitem(self.fp, '_reflns_limit_l_min', str(int(hklmin[2])))
                WriteCIFitem(self.fp, '_reflns_limit_l_max', str(int(hklmax[2])))
            if hklmin is not None:
                WriteCIFitem(self.fp, '_reflns_d_resolution_low  ', G2mth.ValEsd(dmax,-0.009))
                WriteCIFitem(self.fp, '_reflns_d_resolution_high ', G2mth.ValEsd(dmin,-0.009))

        def WritePowderData(histlbl,seq=False):
            'Write out the selected powder diffraction histogram info'
            histblk = self.Histograms[histlbl]
            inst = histblk['Instrument Parameters'][0]
            hId = histblk['hId']
            pfx = ':' + str(hId) + ':'

            if 'Lam1' in inst:
                ratio = self.parmDict.get('I(L2)/I(L1)',inst['I(L2)/I(L1)'][1])
                sratio = self.sigDict.get('I(L2)/I(L1)',-0.0009)
                lam1 = self.parmDict.get('Lam1',inst['Lam1'][1])
                slam1 = self.sigDict.get('Lam1',-0.00009)
                lam2 = self.parmDict.get('Lam2',inst['Lam2'][1])
                slam2 = self.sigDict.get('Lam2',-0.00009)
                # always assume Ka1 & Ka2 if two wavelengths are present
                WriteCIFitem(self.fp, '_diffrn_radiation_type','K\\a~1,2~')
                WriteCIFitem(self.fp, 'loop_' +
                             '\n   _diffrn_radiation_wavelength' +
                             '\n   _diffrn_radiation_wavelength_wt' +
                             '\n   _diffrn_radiation_wavelength_id')
                WriteCIFitem(self.fp, '  ' + PutInCol(G2mth.ValEsd(lam1,slam1),15)+
                             PutInCol('1.0',15) +
                             PutInCol('1',5))
                WriteCIFitem(self.fp, '  ' + PutInCol(G2mth.ValEsd(lam2,slam2),15)+
                             PutInCol(G2mth.ValEsd(ratio,sratio),15)+
                             PutInCol('2',5))
            elif 'Lam' in inst:
                lam1 = self.parmDict.get('Lam',inst['Lam'][1])
                slam1 = self.sigDict.get('Lam',-0.00009)
                WriteCIFitem(self.fp, '_diffrn_radiation_wavelength',G2mth.ValEsd(lam1,slam1))

            if not oneblock:
                if seq:
                    pass
                elif not phasebyhistDict.get(histlbl):
                    WriteCIFitem(self.fp, '\n# No phases associated with this data set')
                else:
                    WriteCIFitem(self.fp, '\n# PHASE TABLE')
                    WriteCIFitem(self.fp, 'loop_' +
                                 '\n   _pd_phase_id' +
                                 '\n   _pd_phase_block_id' +
                                 '\n   _pd_phase_mass_%')
                    wtFrSum = 0.
                    for phasenam in phasebyhistDict.get(histlbl):
                        hapData = self.Phases[phasenam]['Histograms'][histlbl]
                        General = self.Phases[phasenam]['General']
                        wtFrSum += hapData['Scale'][0]*General['Mass']

                    for phasenam in phasebyhistDict.get(histlbl):
                        hapData = self.Phases[phasenam]['Histograms'][histlbl]
                        General = self.Phases[phasenam]['General']
                        wtFr = hapData['Scale'][0]*General['Mass']/wtFrSum
                        pfx = str(self.Phases[phasenam]['pId'])+':'+str(hId)+':'
                        if pfx+'Scale' in self.sigDict:
                            sig = self.sigDict[pfx+'Scale']*wtFr/hapData['Scale'][0]
                        else:
                            sig = -0.0001
                        WriteCIFitem(self.fp,
                            '  '+
                            str(self.Phases[phasenam]['pId']) +
                            '  '+datablockidDict[phasenam]+
                            '  '+G2mth.ValEsd(wtFr,sig)
                            )
                    WriteCIFitem(self.fp, 'loop_' +
                                 '\n   _gsas_proc_phase_R_F_factor' +
                                 '\n   _gsas_proc_phase_R_Fsqd_factor' +
                                 '\n   _gsas_proc_phase_id' +
                                 '\n   _gsas_proc_phase_block_id')
                    for phasenam in phasebyhistDict.get(histlbl):
                        pfx = str(self.Phases[phasenam]['pId'])+':'+str(hId)+':'
                        WriteCIFitem(self.fp,
                            '  '+
                            '  '+G2mth.ValEsd(histblk[pfx+'Rf']/100.,-.00009) +
                            '  '+G2mth.ValEsd(histblk[pfx+'Rf^2']/100.,-.00009)+
                            '  '+str(self.Phases[phasenam]['pId'])+
                            '  '+datablockidDict[phasenam]
                            )
            elif len(self.Phases) == 1:
                # single phase in this histogram
                # get the phase number here
                pId = self.Phases[list(self.Phases.keys())[0]]['pId']
                pfx = str(pId)+':'+str(hId)+':'
                WriteCIFitem(self.fp, '_refine_ls_R_F_factor      ','%.5f'%(histblk[pfx+'Rf']/100.))
                WriteCIFitem(self.fp, '_refine_ls_R_Fsqd_factor   ','%.5f'%(histblk[pfx+'Rf^2']/100.))
                
            try:
                WriteCIFitem(self.fp, '_pd_proc_ls_prof_R_factor   ','%.5f'%(histblk['R']/100.))
                WriteCIFitem(self.fp, '_pd_proc_ls_prof_wR_factor  ','%.5f'%(histblk['wR']/100.))
                WriteCIFitem(self.fp, '_gsas_proc_ls_prof_R_B_factor ','%.5f'%(histblk['Rb']/100.))
                WriteCIFitem(self.fp, '_gsas_proc_ls_prof_wR_B_factor','%.5f'%(histblk['wRb']/100.))
                WriteCIFitem(self.fp, '_pd_proc_ls_prof_wR_expected','%.5f'%(histblk['wRmin']/100.))
            except KeyError:
                pass

            if histblk['Instrument Parameters'][0]['Type'][1][1] == 'X':
                WriteCIFitem(self.fp, '_diffrn_radiation_probe','x-ray')
                pola = histblk['Instrument Parameters'][0].get('Polariz.')
                if pola:
                    pfx = ':' + str(hId) + ':'
                    sig = self.sigDict.get(pfx+'Polariz.',-0.0009)
                    txt = G2mth.ValEsd(pola[1],sig)
                    WriteCIFitem(self.fp, '_diffrn_radiation_polarisn_ratio',txt)
            elif histblk['Instrument Parameters'][0]['Type'][1][1] == 'N':
                WriteCIFitem(self.fp, '_diffrn_radiation_probe','neutron')
            if 'T' in inst['Type'][0]:
                txt = G2mth.ValEsd(inst['2-theta'][0],-0.009)
                WriteCIFitem(self.fp, '_pd_meas_2theta_fixed',txt)

            WriteCIFitem(self.fp, '_pd_proc_ls_background_function',FormatBackground(histblk['Background'],histblk['hId']))

            # TODO: this will need help from Bob
            #WriteCIFitem(self.fp, '_exptl_absorpt_process_details','?')
            #WriteCIFitem(self.fp, '_exptl_absorpt_correction_T_min','?')
            #WriteCIFitem(self.fp, '_exptl_absorpt_correction_T_max','?')
            #C extinction
            #WRITE(IUCIF,'(A)') '# Extinction correction'
            #CALL WRVAL(IUCIF,'_gsas_exptl_extinct_corr_T_min',TEXT(1:10))
            #CALL WRVAL(IUCIF,'_gsas_exptl_extinct_corr_T_max',TEXT(11:20))

            # code removed because it is causing duplication in histogram block 1/26/19 BHT 
            #if not oneblock:                 # instrumental profile terms go here
            #    WriteCIFitem(self.fp, '_pd_proc_ls_profile_function',
            #        FormatInstProfile(histblk["Instrument Parameters"],histblk['hId']))

            #refprx = '_refln.' # mm
            refprx = '_refln_' # normal
            # data collection parameters for the powder dataset

            temperature = histblk['Sample Parameters'].get('Temperature') # G2 uses K
            if not temperature:
                T = '?'
            else:
                T = G2mth.ValEsd(temperature,-0.009,True) # CIF uses K
            WriteCIFitem(self.fp, '_diffrn_ambient_temperature',T)

            pressure = histblk['Sample Parameters'].get('Pressure') #G2 uses mega-Pascal
            if not pressure:
                P = '?'
            else:
                P = G2mth.ValEsd(pressure*1000,-0.09,True) # CIF uses kilopascal (G2 Mpa)
            WriteCIFitem(self.fp, '_diffrn_ambient_pressure',P)

            WriteCIFitem(self.fp, '\n# STRUCTURE FACTOR TABLE')
            # compute maximum intensity reflection
            Imax = 0
            phaselist = []
            for phasenam in histblk['Reflection Lists']:
                try:
                    scale = self.Phases[phasenam]['Histograms'][histlbl]['Scale'][0]
                except KeyError: # reflection table from removed phase?
                    continue
                phaselist.append(phasenam)
                refList = np.asarray(histblk['Reflection Lists'][phasenam]['RefList'])
                I100 = scale*refList.T[8]*refList.T[11]
                #Icorr = np.array([refl[13] for refl in histblk['Reflection Lists'][phasenam]])[0]
                #FO2 = np.array([refl[8] for refl in histblk['Reflection Lists'][phasenam]])
                #I100 = scale*FO2*Icorr
                Imax = max(Imax,max(I100))

            WriteCIFitem(self.fp, 'loop_')
            if len(phaselist) > 1:
                WriteCIFitem(self.fp, '   _pd_refln_phase_id')
            WriteCIFitem(self.fp, '   ' + refprx + 'index_h' +
                         '\n   ' + refprx + 'index_k' +
                         '\n   ' + refprx + 'index_l' +
                         '\n   ' + refprx + 'F_squared_meas' +
                         '\n   ' + refprx + 'F_squared_calc' +
                         '\n   ' + refprx + 'phase_calc' +
                         '\n   _refln_d_spacing')
            if Imax > 0:
                WriteCIFitem(self.fp, '   _gsas_i100_meas')

            refcount = 0
            hklmin = None
            hklmax = None
            dmax = None
            dmin = None
            for phasenam in phaselist:
                scale = self.Phases[phasenam]['Histograms'][histlbl]['Scale'][0]
                phaseid = self.Phases[phasenam]['pId']
                refcount += len(histblk['Reflection Lists'][phasenam]['RefList'])
                refList = np.asarray(histblk['Reflection Lists'][phasenam]['RefList'])
                I100 = scale*refList.T[8]*refList.T[11]
                for j,ref in enumerate(histblk['Reflection Lists'][phasenam]['RefList']):
                    if DEBUG:
                        print('DEBUG: skipping reflection list')
                        break
                    if hklmin is None:
                        hklmin = copy.copy(ref[0:3])
                        hklmax = copy.copy(ref[0:3])
                    if dmin is None:
                         dmax = dmin = ref[4]
                    if len(phaselist) > 1:
                        s = PutInCol(phaseid,2)
                    else:
                        s = ""
                    for i,hkl in enumerate(ref[0:3]):
                        hklmax[i] = max(hkl,hklmax[i])
                        hklmin[i] = min(hkl,hklmin[i])
                        s += PutInCol(int(hkl),4)
                    for I in ref[8:10]:
                        s += PutInCol(G2mth.ValEsd(I,-0.0009),10)
                    s += PutInCol(G2mth.ValEsd(ref[10],-0.9),7)
                    dmax = max(dmax,ref[4])
                    dmin = min(dmin,ref[4])
                    s += PutInCol(G2mth.ValEsd(ref[4],-0.00009),8)
                    if Imax > 0:
                        s += PutInCol(G2mth.ValEsd(100.*I100[j]/Imax,-0.09),6)
                    WriteCIFitem(self.fp, "  "+s)

            WriteReflStat(refcount,hklmin,hklmax,dmin,dmax,len(phaselist))
            WriteCIFitem(self.fp, '\n# POWDER DATA TABLE')
            # is data fixed step? If the step varies by <0.01% treat as fixed step
            steps = abs(histblk['Data'][0][1:] - histblk['Data'][0][:-1])
            if (max(steps)-min(steps)) > np.mean(steps)/10000.:
                fixedstep = False
            else:
                fixedstep = True

            zero = None
            if fixedstep and 'T' not in inst['Type'][0]: # and not TOF
                WriteCIFitem(self.fp, '_pd_meas_2theta_range_min', G2mth.ValEsd(histblk['Data'][0][0],-0.00009))
                WriteCIFitem(self.fp, '_pd_meas_2theta_range_max', G2mth.ValEsd(histblk['Data'][0][-1],-0.00009))
                WriteCIFitem(self.fp, '_pd_meas_2theta_range_inc', G2mth.ValEsd(np.mean(steps),-0.00009))
                # zero correct, if defined
                zerolst = histblk['Instrument Parameters'][0].get('Zero')
                if zerolst: zero = zerolst[1]
                zero = self.parmDict.get('Zero',zero)
                if zero:
                    WriteCIFitem(self.fp, '_pd_proc_2theta_range_min', G2mth.ValEsd(histblk['Data'][0][0]-zero,-0.00009))
                    WriteCIFitem(self.fp, '_pd_proc_2theta_range_max', G2mth.ValEsd(histblk['Data'][0][-1]-zero,-0.00009))
                    WriteCIFitem(self.fp, '_pd_proc_2theta_range_inc', G2mth.ValEsd(steps.sum()/len(steps),-0.00009))

            if zero:
                WriteCIFitem(self.fp, '_pd_proc_number_of_points', str(len(histblk['Data'][0])))
            else:
                WriteCIFitem(self.fp, '_pd_meas_number_of_points', str(len(histblk['Data'][0])))
            WriteCIFitem(self.fp, '\nloop_')
            #            WriteCIFitem(self.fp, '   _pd_proc_d_spacing') # need easy way to get this
            if not fixedstep:
                if zero:
                    WriteCIFitem(self.fp, '   _pd_proc_2theta_corrected')
                elif 'T' in inst['Type'][0]: # and not TOF
                    WriteCIFitem(self.fp, '   _pd_meas_time_of_flight')
                else:
                    WriteCIFitem(self.fp, '   _pd_meas_2theta_scan')
            # at least for now, always report weights.
            #if countsdata:
            #    WriteCIFitem(self.fp, '   _pd_meas_counts_total')
            #else:
            WriteCIFitem(self.fp, '   _pd_meas_intensity_total')
            WriteCIFitem(self.fp, '   _pd_calc_intensity_total')
            WriteCIFitem(self.fp, '   _pd_proc_intensity_bkg_calc')
            WriteCIFitem(self.fp, '   _pd_proc_ls_weight')
            maxY = max(histblk['Data'][1].max(),histblk['Data'][3].max())
            if maxY < 0: maxY *= -10 # this should never happen, but...
            ndec = max(0,10-int(np.log10(maxY))-1) # 10 sig figs should be enough
            maxSU = histblk['Data'][2].max()
            if maxSU < 0: maxSU *= -1 # this should never happen, but...
            ndecSU = max(0,8-int(np.log10(maxSU))-1) # 8 sig figs should be enough
            lowlim,highlim = histblk['Limits'][1]

            if DEBUG:
                print('DEBUG: skipping profile list')
            else:
                for x,yobs,yw,ycalc,ybkg in zip(histblk['Data'][0].data,        #get the data from these masked arrays
                                                histblk['Data'][1].data,
                                                histblk['Data'][2].data,
                                                histblk['Data'][3].data,
                                                histblk['Data'][4].data):
                    if lowlim <= x <= highlim:
                        pass
                    else:
                        yw = 0.0 # show the point is not in use

                    if fixedstep:
                        s = ""
                    elif zero:
                        s = PutInCol(G2mth.ValEsd(x-zero,-0.00009),10)
                    else:
                        s = PutInCol(G2mth.ValEsd(x,-0.00009),10)
                    s += PutInCol(Yfmt(ndec,yobs),12)
                    s += PutInCol(Yfmt(ndec,ycalc),12)
                    s += PutInCol(Yfmt(ndec,ybkg),11)
                    s += PutInCol(Yfmt(ndecSU,yw),9)
                    WriteCIFitem(self.fp, "  "+s)

        def WriteSingleXtalData(histlbl):
            'Write out the selected single crystal histogram info'
            histblk = self.Histograms[histlbl]

            #refprx = '_refln.' # mm
            refprx = '_refln_' # normal

            WriteCIFitem(self.fp, '\n# STRUCTURE FACTOR TABLE')
            WriteCIFitem(self.fp, 'loop_' +
                         '\n   ' + refprx + 'index_h' +
                         '\n   ' + refprx + 'index_k' +
                         '\n   ' + refprx + 'index_l' +
                         '\n   ' + refprx + 'F_squared_meas' +
                         '\n   ' + refprx + 'F_squared_sigma' +
                         '\n   ' + refprx + 'F_squared_calc' +
                         '\n   ' + refprx + 'phase_calc'
                         )

            hklmin = None
            hklmax = None
            dmax = None
            dmin = None
            refcount = len(histblk['Data']['RefList'])
            for ref in histblk['Data']['RefList']:
                if ref[3] <= 0:      #skip user rejected reflections (mul <= 0)
                    continue
                s = "  "
                if hklmin is None:
                    hklmin = copy.copy(ref[0:3])
                    hklmax = copy.copy(ref[0:3])
                    dmax = dmin = ref[4]
                for i,hkl in enumerate(ref[0:3]):
                    hklmax[i] = max(hkl,hklmax[i])
                    hklmin[i] = min(hkl,hklmin[i])
                    s += PutInCol(int(hkl),4)
                if ref[5] == 0.0:
                    s += PutInCol(G2mth.ValEsd(ref[8],0),12)
                    s += PutInCol('.',10)
                    s += PutInCol(G2mth.ValEsd(ref[9],0),12)
                else:
                    sig = ref[6] * ref[8] / ref[5]
                    s += PutInCol(G2mth.ValEsd(ref[8],-abs(sig/10)),12)
                    s += PutInCol(G2mth.ValEsd(sig,-abs(sig)/10.),10)
                    s += PutInCol(G2mth.ValEsd(ref[9],-abs(sig/10)),12)
                s += PutInCol(G2mth.ValEsd(ref[10],-0.9),7)
                dmax = max(dmax,ref[4])
                dmin = min(dmin,ref[4])
                WriteCIFitem(self.fp, s)
            if not self.quickmode: # statistics only in a full CIF
                WriteReflStat(refcount,hklmin,hklmax,dmin,dmax)
                hId = histblk['hId']
                hfx = '0:'+str(hId)+':'
                phfx = '%d:%d:'%(0,hId)
                extType,extModel,extParms = self.Phases[phasenam]['Histograms'][histlbl]['Extinction']
                if extModel != 'None':
                    WriteCIFitem(self.fp, '# Extinction scaled by 1.e5')
                    WriteCIFitem(self.fp, '_refine_ls_extinction_method','Becker-Coppens %s %s'%(extModel,extType))
                    sig = -1.e-3
                    if extModel == 'Primary':
                        parm = extParms['Ep'][0]*1.e5
                        if extParms['Ep'][1]:
                            sig = self.sigDict[phfx+'Ep']*1.e5
                        text = G2mth.ValEsd(parm,sig)
                    elif extModel == 'Secondary Type I':
                        parm = extParms['Eg'][0]*1.e5
                        if extParms['Eg'][1]:
                            sig = self.sigDict[phfx+'Eg']*1.e5
                        text = G2mth.ValEsd(parm,sig)
                    elif extModel == 'Secondary Type II':
                        parm = extParms['Es'][0]*1.e5
                        if extParms['Es'][1]:
                            sig = self.sigDict[phfx+'Es']*1.e5
                        text = G2mth.ValEsd(parm,sig)
                    elif extModel == 'Secondary Type I & II':
                        parm = extParms['Eg'][0]*1.e5
                        if extParms['Es'][1]:
                            sig = self.sigDict[phfx+'Es']*1.e5
                        text = G2mth.ValEsd(parm,sig)
                        sig = -1.0e-3
                        parm = extParms['Es'][0]*1.e5
                        if extParms['Es'][1]:
                            sig = self.sigDict[phfx+'Es']*1.e5
                        text += G2mth.ValEsd(parm,sig)
                    WriteCIFitem(self.fp, '_refine_ls_extinction_coef',text)
                    WriteCIFitem(self.fp, '_refine_ls_extinction_expression','Becker & Coppens (1974). Acta Cryst. A30, 129-147')

                WriteCIFitem(self.fp, '_refine_ls_wR_factor_gt    ','%.4f'%(histblk['wR']/100.))
                WriteCIFitem(self.fp, '_refine_ls_R_factor_gt     ','%.4f'%(histblk[hfx+'Rf']/100.))
                WriteCIFitem(self.fp, '_refine_ls_R_Fsqd_factor   ','%.4f'%(histblk[hfx+'Rf^2']/100.))
        def EditAuthor(event=None):
            'dialog to edit the CIF author info'
            'Edit the CIF author name'
            dlg = G2G.SingleStringDialog(self.G2frame,
                                          'Get CIF Author',
                                          'Provide CIF Author name (Last, First)',
                                          value=self.author)
            if not dlg.Show():
                dlg.Destroy()
                return False  # cancel was pressed
            self.author = dlg.GetValue()
            self.shortauthorname = self.author.replace(',','').replace(' ','')[:20]
            dlg.Destroy()
            try:
                self.OverallParms['Controls']["Author"] = self.author # save for future
            except KeyError:
                pass
            return True

        def EditInstNames(event=None):
            'Provide a dialog for editing instrument names; for sequential fit, only need one name'
            dictlist = []
            keylist = []
            lbllist = []
            for hist in sorted(self.Histograms):
                if hist.startswith("PWDR"):
                    key2 = "Sample Parameters"
                    d = self.Histograms[hist][key2]
                elif hist.startswith("HKLF"):
                    key2 = "Instrument Parameters"
                    d = self.Histograms[hist][key2][0]

                lbllist.append(hist)
                dictlist.append(d)
                keylist.append('InstrName')
                instrname = d.get('InstrName')
                if instrname is None:
                    d['InstrName'] = ''
                if hist.startswith("PWDR") and seqmode: break                
            return G2G.CallScrolledMultiEditor(
                self.G2frame,dictlist,keylist,
                prelbl=range(1,len(dictlist)+1),
                postlbl=lbllist,
                title='Instrument names',
                header="Edit instrument names. Note that a non-blank\nname is required for all histograms",
                CopyButton=True,ASCIIonly=True)

        def EditRanges(event):
            '''Edit the bond distance/angle search range; phase is determined from
            a pointer placed in the button object (.phasedict) that references the
            phase dictionary
            '''
            but = event.GetEventObject()
            phasedict = but.phasedict
            dlg = G2G.DisAglDialog(
                self.G2frame,
                phasedict['General']['DisAglCtls'], # edited
                phasedict['General'], # defaults
                )
            if dlg.ShowModal() == wx.ID_OK:
                phasedict['General']['DisAglCtls'] = dlg.GetData()
            dlg.Destroy()
            
        def SetCellT(event):
            '''Set the temperature value by selection of a histogram
            '''
            but = event.GetEventObject()
            phasenam = but.phase
            rId =  self.Phases[phasenam]['ranId']
            self.CellHistSelection[rId] = self._CellSelectHist(phasenam)
            
        def EditCIFDefaults():
            '''Fills the CIF Defaults window with controls for editing various CIF export
            parameters (mostly related to templates).
            '''
            self.cifdefs.DestroyChildren()
            self.cifdefs.SetTitle('Edit CIF settings')
            vbox = wx.BoxSizer(wx.VERTICAL)
            vbox.Add(wx.StaticText(self.cifdefs, wx.ID_ANY,'Creating file '+self.filename))
            but = wx.Button(self.cifdefs, wx.ID_ANY,'Edit CIF Author')
            but.Bind(wx.EVT_BUTTON,EditAuthor)
            vbox.Add(but,0,wx.ALIGN_CENTER,3)
            but = wx.Button(self.cifdefs, wx.ID_ANY,'Edit Instrument Name(s)')
            but.Bind(wx.EVT_BUTTON,EditInstNames)
            vbox.Add(but,0,wx.ALIGN_CENTER,3)
            cpnl = wxscroll.ScrolledPanel(self.cifdefs,size=(300,300))
            cbox = wx.BoxSizer(wx.VERTICAL)
            G2G.HorizontalLine(cbox,cpnl)
            cbox.Add(
                CIFtemplateSelect(self.cifdefs,
                                  cpnl,'publ',self.OverallParms['Controls'],
                                  EditCIFDefaults,
                                  "Publication (overall) template",
                                  ),
                0,wx.EXPAND|wx.ALIGN_LEFT|wx.ALL)
            for phasenam in sorted(self.Phases.keys()):
                G2G.HorizontalLine(cbox,cpnl)
                title = 'Phase '+phasenam
                phasedict = self.Phases[phasenam] # pointer to current phase info
                cbox.Add(
                    CIFtemplateSelect(self.cifdefs,
                                      cpnl,'phase',phasedict['General'],
                                      EditCIFDefaults,
                                      title,
                                      phasenam),
                    0,wx.EXPAND|wx.ALIGN_LEFT|wx.ALL)
                cpnl.SetSizer(cbox)
                if phasedict['General']['Type'] == 'nuclear':
                    but = wx.Button(cpnl, wx.ID_ANY,'Edit distance/angle ranges')
                    cbox.Add(but,0,wx.ALIGN_LEFT,0)
                    cbox.Add((-1,2))
                    but.phasedict = self.Phases[phasenam]  # set a pointer to current phase info
                    but.Bind(wx.EVT_BUTTON,EditRanges)     # phase bond/angle ranges
                    but = wx.Button(cpnl, wx.ID_ANY,'Set distance/angle publication flags')
                    but.phase = phasenam  # set a pointer to current phase info
                    but.Bind(wx.EVT_BUTTON,SelectDisAglFlags)     # phase bond/angle ranges
                    cbox.Add(but,0,wx.ALIGN_LEFT,0)
                if self._CellSelectNeeded(phasenam):
                    but = wx.Button(cpnl, wx.ID_ANY,'Select cell temperature')
                    cbox.Add(but,0,wx.ALIGN_LEFT,0)
                    cbox.Add((-1,2))
                    but.phase = phasenam  # set a pointer to current phase info
                    but.Bind(wx.EVT_BUTTON,SetCellT)
                cbox.Add((-1,2))
            for i in sorted(self.powderDict.keys()):
                G2G.HorizontalLine(cbox,cpnl)
                if seqmode:
                    hist = self.powderDict[i]
                    histblk = self.Histograms[hist]
                    title = 'All Powder datasets'
                    self.seqSmplParms = {}
                    cbox.Add(
                        CIFtemplateSelect(self.cifdefs,
                                      cpnl,'powder',self.seqSmplParms,
                                      EditCIFDefaults,
                                      title,
                                      histblk["Sample Parameters"]['InstrName']),
                        0,wx.EXPAND|wx.ALIGN_LEFT|wx.ALL)
                    break
                hist = self.powderDict[i]
                histblk = self.Histograms[hist]
                title = 'Powder dataset '+hist[5:]
                cbox.Add(
                    CIFtemplateSelect(self.cifdefs,
                                      cpnl,'powder',histblk["Sample Parameters"],
                                      EditCIFDefaults,
                                      title,
                                      histblk["Sample Parameters"]['InstrName']),
                    0,wx.EXPAND|wx.ALIGN_LEFT|wx.ALL)
            for i in sorted(self.xtalDict.keys()):
                G2G.HorizontalLine(cbox,cpnl)
                hist = self.xtalDict[i]
                histblk = self.Histograms[hist]
                title = 'Single Xtal dataset '+hist[5:]
                cbox.Add(
                    CIFtemplateSelect(self.cifdefs,
                                      cpnl,'single',histblk["Instrument Parameters"][0],
                                      EditCIFDefaults,
                                      title,
                                      histblk["Instrument Parameters"][0]['InstrName']),
                    0,wx.EXPAND|wx.ALIGN_LEFT|wx.ALL)
            cpnl.SetSizer(cbox)
            cpnl.SetAutoLayout(1)
            cpnl.SetupScrolling()
            #cpnl.Bind(rw.EVT_RW_LAYOUT_NEEDED, self.OnLayoutNeeded) # needed if sizes change
            cpnl.Layout()

            vbox.Add(cpnl, 1, wx.ALIGN_LEFT|wx.ALL|wx.EXPAND, 0)
            btnsizer = wx.StdDialogButtonSizer()
            btn = wx.Button(self.cifdefs, wx.ID_OK, "Create CIF")
            btn.SetDefault()
            btnsizer.AddButton(btn)
            btn = wx.Button(self.cifdefs, wx.ID_CANCEL)
            btnsizer.AddButton(btn)
            btnsizer.Realize()
            vbox.Add(btnsizer, 0, wx.ALIGN_CENTER|wx.ALL, 5)
            self.cifdefs.SetSizer(vbox)
            vbox.Fit(self.cifdefs)
            self.cifdefs.Layout()

        def OnToggleButton(event):
            'Respond to press of ToggleButton in SelectDisAglFlags'
            but = event.GetEventObject()
            if but.GetValue():
                but.DisAglSel[but.key] = True
            else:
                try:
                    del but.DisAglSel[but.key]
                except KeyError:
                    pass
        def keepTrue(event):
            event.GetEventObject().SetValue(True)
        def keepFalse(event):
            event.GetEventObject().SetValue(False)

        def SelectDisAglFlags(event):
            'Select Distance/Angle use flags for the selected phase'
            phasenam = event.GetEventObject().phase
            phasedict = self.Phases[phasenam]
            SymOpList,offsetList,symOpList,G2oprList,G2opcodes = G2spc.AllOps(phasedict['General']['SGData'])
            generalData = phasedict['General']
            # create a dict for storing Pub flag for bonds/angles, if needed
            if phasedict['General'].get("DisAglHideFlag") is None:
                phasedict['General']["DisAglHideFlag"] = {}
            DisAngSel = phasedict['General']["DisAglHideFlag"]

            cx,ct,cs,cia = phasedict['General']['AtomPtrs']
            cn = ct-1
            cfrac = cx+3
            DisAglData = {}
            # create a list of atoms, but skip atoms with zero occupancy
            xyz = []
            fpfx = str(phasedict['pId'])+'::Afrac:'
            for i,atom in enumerate(phasedict['Atoms']):
                if self.parmDict.get(fpfx+str(i),atom[cfrac]) == 0.0: continue
                xyz.append([i,]+atom[cn:cn+2]+atom[cx:cx+3])
            if 'DisAglCtls' not in generalData:
                # should not be used, since DisAglDialog should be called
                # for all phases before getting here
                dlg = G2G.DisAglDialog(
                    self.cifdefs,
                    {},
                    generalData)
                if dlg.ShowModal() == wx.ID_OK:
                    generalData['DisAglCtls'] = dlg.GetData()
                else:
                    dlg.Destroy()
                    return
                dlg.Destroy()
            dlg = wx.Dialog(
                self.G2frame,
                style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
            vbox = wx.BoxSizer(wx.VERTICAL)
            txt = wx.StaticText(dlg,wx.ID_ANY,'Searching distances for phase '+phasenam
                                +'\nPlease wait...')
            vbox.Add(txt,0,wx.ALL|wx.EXPAND)
            dlg.SetSizer(vbox)
            dlg.CenterOnParent()
            dlg.Show() # post "please wait"
            wx.BeginBusyCursor() # and change cursor

            DisAglData['OrigAtoms'] = xyz
            DisAglData['TargAtoms'] = xyz
            SymOpList,offsetList,symOpList,G2oprList,G2opcodes = G2spc.AllOps(
                generalData['SGData'])

#            xpandSGdata = generalData['SGData'].copy()
#            xpandSGdata.update({'SGOps':symOpList,
#                                'SGInv':False,
#                                'SGLatt':'P',
#                                'SGCen':np.array([[0, 0, 0]]),})
#            DisAglData['SGData'] = xpandSGdata
            DisAglData['SGData'] = generalData['SGData'].copy()

            DisAglData['Cell'] = generalData['Cell'][1:] #+ volume
            if 'pId' in phasedict:
                DisAglData['pId'] = phasedict['pId']
                DisAglData['covData'] = self.OverallParms['Covariance']
            try:
                AtomLabels,DistArray,AngArray = G2stMn.RetDistAngle(
                    generalData['DisAglCtls'],
                    DisAglData)
            except KeyError:        # inside DistAngle for missing atom types in DisAglCtls
                print('**** ERROR - try again but do "Reset" to fill in missing atom types ****')
            wx.EndBusyCursor()
            txt.SetLabel('Set publication flags for distances and angles in\nphase '+phasenam)
            vbox.Add((5,5))
            vbox.Add(wx.StaticText(dlg,wx.ID_ANY,
                                   'The default is to flag all distances and angles as to be'+
                                   '\npublished. Change this by pressing appropriate buttons.'),
                     0,wx.ALL|wx.EXPAND)
            hbox = wx.BoxSizer(wx.HORIZONTAL)
            vbox.Add(hbox)
            hbox.Add(wx.StaticText(dlg,wx.ID_ANY,'Button appearance: '))
            but = wx.ToggleButton(dlg,wx.ID_ANY,'Publish')
            but.Bind(wx.EVT_TOGGLEBUTTON,keepFalse)
            hbox.Add(but)
            but = wx.ToggleButton(dlg,wx.ID_ANY,"Don't publish")
            but.Bind(wx.EVT_TOGGLEBUTTON,keepTrue)
            hbox.Add(but)
            but.SetValue(True)
            G2G.HorizontalLine(vbox,dlg)

            cpnl = wxscroll.ScrolledPanel(dlg,size=(400,300))
            cbox = wx.BoxSizer(wx.VERTICAL)
            for c in sorted(DistArray):
                karr = []
                UsedCols = {}
                cbox.Add(wx.StaticText(cpnl,wx.ID_ANY,
                                   'distances to/angles around atom '+AtomLabels[c]))
                #dbox = wx.GridBagSizer(hgap=5)
                dbox = wx.GridBagSizer()
                for i,D in enumerate(DistArray[c]):
                    karr.append(tuple(D[0:3]))
                    val = "{:.2f}".format(D[3])
                    sym = " [{:d} {:d} {:d}]".format(*D[1]) + " #{:d}".format(D[2])
                    dbox.Add(wx.StaticText(cpnl,wx.ID_ANY,AtomLabels[D[0]]),
                             (i+1,0)
                             )
                    dbox.Add(wx.StaticText(cpnl,wx.ID_ANY,sym),
                             (i+1,1)
                             )
                    but = wx.ToggleButton(cpnl,wx.ID_ANY,val)
                    but.key = (c,karr[-1])
                    but.DisAglSel = DisAngSel
                    if DisAngSel.get(but.key): but.SetValue(True)
                    but.Bind(wx.EVT_TOGGLEBUTTON,OnToggleButton)
                    dbox.Add(but,(i+1,2),border=1)
                for i,D in enumerate(AngArray[c]):
                    val = "{:.1f}".format(D[2][0])
                    but = wx.ToggleButton(cpnl,wx.ID_ANY,val)
                    but.key = (karr[D[0]],c,karr[D[1]])
                    but.DisAglSel = DisAngSel
                    if DisAngSel.get(but.key): but.SetValue(True)
                    but.Bind(wx.EVT_TOGGLEBUTTON,OnToggleButton)
                    dbox.Add(but,(D[0]+1,D[1]+3),border=1)
                    UsedCols[D[1]+3] = True
                for i,D in enumerate(DistArray[c][:-1]): # label columns that are used
                    if UsedCols.get(i+3):
                        dbox.Add(wx.StaticText(cpnl,wx.ID_ANY,AtomLabels[D[0]]),
                                 (0,i+3),
                                 flag=wx.ALIGN_CENTER
                                 )
                dbox.Add(wx.StaticText(cpnl,wx.ID_ANY,'distance'),
                                 (0,2),
                                 flag=wx.ALIGN_CENTER
                                 )
                cbox.Add(dbox)
                G2G.HorizontalLine(cbox,cpnl)
            cpnl.SetSizer(cbox)
            cpnl.SetAutoLayout(1)
            cpnl.SetupScrolling()
            #cpnl.Bind(rw.EVT_RW_LAYOUT_NEEDED, self.OnLayoutNeeded) # needed if sizes change
            cpnl.Layout()

            vbox.Add(cpnl, 1, wx.ALIGN_LEFT|wx.ALL|wx.EXPAND, 0)

            btnsizer = wx.StdDialogButtonSizer()
            btn = wx.Button(dlg, wx.ID_OK, "Done")
            btn.SetDefault()
            btnsizer.AddButton(btn)
            btnsizer.Realize()
            vbox.Add(btnsizer, 0, wx.ALIGN_CENTER|wx.ALL, 5)
            dlg.SetSizer(vbox)
            vbox.Fit(dlg)
            dlg.Layout()

            dlg.CenterOnParent()
            dlg.ShowModal()

#==============================================================================
####  _Exporter code starts here         ======================================
#==============================================================================
        # make sure required information is present
        self.CIFdate = dt.datetime.strftime(dt.datetime.now(),"%Y-%m-%dT%H:%M")
        if not self.CIFname: # Get a name for the CIF. If not defined, use the GPX name (save, if that is needed).
            if not self.G2frame.GSASprojectfile:
                self.G2frame.OnFileSaveas(None)
            if not self.G2frame.GSASprojectfile: return
            self.CIFname = os.path.splitext(
                os.path.split(self.G2frame.GSASprojectfile)[1]
                )[0]
            self.CIFname = self.CIFname.replace(' ','')
        # replace non-ASCII characters in CIFname with dots
        s = ''
        for c in self.CIFname:
            if ord(c) < 128:
                s += c
            else:
                s += '.'
        self.CIFname = s
        
        #=================================================================
        # write quick CIFs
        #=================================================================
        if phaseOnly: #====Phase only CIF ================================
            print('Writing CIF output to file '+self.filename)
            oneblock = True
            self.quickmode = True
            self.Write(' ')
            self.Write(70*'#')
            WriteCIFitem(self.fp, 'data_'+phaseOnly.replace(' ','_'))
            #phaseblk = self.Phases[phaseOnly] # pointer to current phase info
            # report the phase info
            WritePhaseInfo(phaseOnly)
            return
        elif histOnly: #====Histogram only CIF ================================
            print('Writing CIF output to file '+self.filename)
            hist = histOnly
            #histname = histOnly.replace(' ','')
            oneblock = True
            self.quickmode = True
            self.ifHKLF = False
            self.ifPWDR = True
            self.Write(' ')
            self.Write(70*'#')
            #phasenam = self.Phases.keys()[0]
            WriteCIFitem(self.fp, 'data_'+self.CIFname)
            if hist.startswith("PWDR"):
                WritePowderData(hist)
            elif hist.startswith("HKLF"):
                WriteSingleXtalData(hist)
            return
        #===============================================================================
        # setup for sequential fits here
        #===============================================================================
        seqmode = False
        seqHistList = self.G2frame.testSeqRefineMode()
        if seqHistList:
            if self.seqData is None:
                raise Exception('Use Export/Sequential project for sequential refinements')
            phaseWithHist = True   # include the phase in the same block as the histogram
            if len(self.Phases) > 1:
                phaseWithHist = False  # multiple phases per histogram
            seqmode = True
        #===============================================================================
        # the export process for a full CIF starts here (Sequential too)
        #===============================================================================
        # load saved CIF author name
        self.author = self.OverallParms['Controls'].get("Author",'?').strip()
        # initialize dict for Selection of Hist for unit cell reporting
        self.OverallParms['Controls']['CellHistSelection'] = self.OverallParms[
            'Controls'].get('CellHistSelection',{})
        self.CellHistSelection = self.OverallParms['Controls']['CellHistSelection']
        # create a dict with refined values and their uncertainties
        self.loadParmDict()
        # is there anything to export?
        if len(self.Phases) == len(self.powderDict) == len(self.xtalDict) == 0:
           self.G2frame.ErrorDialog(
               'Empty project',
               'Project does not contain any data or phases. Are they interconnected?')
           return
        if self.ExportSelect('ask'): return
        if not self.filename:
            print('No name supplied')
            return
        self.OpenFile()
        
        #if self.ExportSelect('default'): return
        # Someday: get restraint & constraint info
        #restraintDict = self.OverallParms.get('Restraints',{})
        #for i in  self.OverallParms['Constraints']:
        #    print i
        #    for j in self.OverallParms['Constraints'][i]:
        #        print j

        self.quickmode = False # full CIF
        phasenam = None # include all phases
        # Will this require a multiblock CIF?
        if len(self.Phases) > 1:
            oneblock = False
        elif len(self.powderDict) + len(self.xtalDict) > 1:
            oneblock = False
        else: # one phase, one dataset, Full CIF
            oneblock = True

        # check there is an instrument name for every histogram
        self.ifPWDR = False
        self.ifHKLF = False
        invalid = 0
        key3 = 'InstrName'
        for hist in self.Histograms:
            if hist.startswith("PWDR"):
                self.ifPWDR = True
                key2 = "Sample Parameters"
                d = self.Histograms[hist][key2]
            elif hist.startswith("HKLF"):
                self.ifHKLF = True
                key2 = "Instrument Parameters"
                d = self.Histograms[hist][key2][0]
            instrname = d.get(key3)
            if instrname is None:
                d[key3] = ''
                invalid += 1
            elif instrname.strip() == '':
                invalid += 1
            if hist.startswith("PWDR") and seqmode: break
        if invalid:
            #msg = ""
            #if invalid > 3: msg = (
            #    "\n\nNote: it may be faster to set the name for\n"
            #    "one histogram for each instrument and use the\n"
            #    "File/Copy option to duplicate the name"
            #    )
            if not EditInstNames(): return

        # check for a distance-angle range search range for each phase
        for phasenam in sorted(self.Phases.keys()):
            #i = self.Phases[phasenam]['pId']
            phasedict = self.Phases[phasenam] # pointer to current phase info
            if 'DisAglCtls' not in phasedict['General']:
                dlg = G2G.DisAglDialog(
                    self.G2frame,
                    {},
                    phasedict['General'])
                if dlg.ShowModal() == wx.ID_OK:
                    phasedict['General']['DisAglCtls'] = dlg.GetData()
                else:
                    dlg.Destroy()
                    return
                dlg.Destroy()
                    
        # check if temperature values & pressure are defaulted
        default = 0
        for hist in self.Histograms:
            if hist.startswith("PWDR"):
                key2 = "Sample Parameters"
                T = self.Histograms[hist][key2].get('Temperature')
                if not T:
                    default += 1
                elif T == 300:
                    default += 1
                P = self.Histograms[hist][key2].get('Pressure')
                if not P:
                    default += 1
                elif P == 1:
                    default += 1
        if default > 0:
            dlg = wx.MessageDialog(
                self.G2frame,
                'Temperature/Pressure values appear to be defaulted for some powder histograms (See Sample Parameters for each PWDR tree entry). Do you want to use those values?',
                'Check T and P values',
                wx.OK|wx.CANCEL)
            ret = dlg.ShowModal()
            dlg.CenterOnParent()
            dlg.Destroy()
            if ret != wx.ID_OK: return
        if oneblock:
            # select a dataset to use (there should only be one set in one block,
            # but take whatever comes 1st)
            for hist in self.Histograms:
                histblk = self.Histograms[hist]
                if hist.startswith("PWDR"):
                    instnam = histblk["Sample Parameters"]['InstrName']
                    break # ignore all but 1st data histogram
                elif hist.startswith("HKLF"):
                    instnam = histblk["Instrument Parameters"][0]['InstrName']
                    break # ignore all but 1st data histogram
        # give the user a window to edit CIF contents
        if not self.author:
            self.author = self.OverallParms['Controls'].get("Author",'?').strip()
        if not self.author:
            if not EditAuthor(): return
        self.ValidateAscii([('Author name',self.author),]) # check for ASCII strings where needed, warn on problems
        self.shortauthorname = self.author.replace(',','').replace(' ','')[:20]
        self.cifdefs = wx.Dialog(
            self.G2frame,
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
        self.cifdefs.G2frame = self.G2frame
        self.cifdefs.CenterOnParent()
        EditCIFDefaults()
        if self.cifdefs.ShowModal() != wx.ID_OK:
            self.cifdefs.Destroy()
            return
        while self.ValidateAscii([('Author name',self.author),
                                  ]): # validate a few things as ASCII
            if self.cifdefs.ShowModal() != wx.ID_OK:
                self.cifdefs.Destroy()
                return
        self.cifdefs.Destroy()
        #======================================================================
        #---- Start writing the CIF - single block
        #======================================================================
        print('Writing CIF output to file '+self.filename+"...")
        if self.currentExportType == 'single' or self.currentExportType == 'powder':
            #======Data only CIF (powder/xtal) ====================================
            hist = self.histnam[0]
            self.CIFname = hist[5:40].replace(' ','')
            WriteCIFitem(self.fp, 'data_'+self.CIFname)
            if hist.startswith("PWDR"):
                WritePowderData(hist)
            elif hist.startswith("HKLF"):
                WriteSingleXtalData(hist)
            else:
                print ("should not happen")
        elif oneblock:
            #====Single block, data & phase CIF ===================================
            WriteCIFitem(self.fp, 'data_'+self.CIFname)
            if phasenam is None: # if not already selected, select the first phase (should be one)
                phasenam = self.Phases.keys()[0]
            #print 'phasenam',phasenam
            #phaseblk = self.Phases[phasenam] # pointer to current phase info
            instnam = instnam.replace(' ','')
            WriteCIFitem(self.fp, '_pd_block_id',
                         str(self.CIFdate) + "|" + str(self.CIFname) + "|" +
                         str(self.shortauthorname) + "|" + instnam)
            WriteAudit()
            writeCIFtemplate(self.OverallParms['Controls'],'publ') # overall (publication) template
            WriteOverall()
            writeCIFtemplate(self.Phases[phasenam]['General'],'phase',phasenam) # write phase template
            # report the phase info
            WritePhaseInfo(phasenam,False)
            if hist.startswith("PWDR"):  # this is invoked for single-block CIFs
                # preferred orientation
                SH = FormatSH(phasenam)
                MD = FormatHAPpo(phasenam)
                if SH and MD:
                    WriteCIFitem(self.fp, '_pd_proc_ls_pref_orient_corr', SH + '\n' + MD)
                elif SH or MD:
                    WriteCIFitem(self.fp, '_pd_proc_ls_pref_orient_corr', SH + MD)
                else:
                    WriteCIFitem(self.fp, '_pd_proc_ls_pref_orient_corr', 'none')
                # report profile, since one-block: include both histogram and phase info (N.B. there is only 1 of each)
                WriteCIFitem(self.fp, '_pd_proc_ls_profile_function',
                    FormatInstProfile(histblk["Instrument Parameters"],histblk['hId'])
                    +'\n'+FormatPhaseProfile(phasenam))

                histblk = self.Histograms[hist]["Sample Parameters"]
                writeCIFtemplate(histblk,'powder',histblk['InstrName']) # write powder template
                WritePowderData(hist)
            elif hist.startswith("HKLF"):
                histprm = self.Histograms[hist]["Instrument Parameters"][0]
                writeCIFtemplate(histprm,'single',histprm['InstrName']) # single crystal template
                WriteSingleXtalData(hist)
        elif seqHistList:
            #---- sequential fit project (multiblock)  ====================
            phasebyhistDict = {} # create a cross-reference to phases by histogram
            for phasenam in sorted(self.Phases.keys()):
                rId = phasedict['ranId']
                if rId in self.CellHistSelection: continue
                self.CellHistSelection[rId] = self._CellSelectHist(phasenam)
            nsteps = 1 + len(self.Phases) + len(self.powderDict) + len(self.xtalDict)
            try:
                dlg = wx.ProgressDialog('CIF progress','starting',nsteps,parent=self.G2frame)
                dlg.CenterOnParent()

                # publication info
                step = 1
                dlg.Update(step,"Exporting overall section")
                WriteCIFitem(self.fp, '\ndata_'+self.CIFname+'_publ')
                WriteAudit()
                WriteCIFitem(self.fp, '_pd_block_id',
                             str(self.CIFdate) + "|" + str(self.CIFname) + "|" +
                             str(self.shortauthorname) + "|Overall")
                writeCIFtemplate(self.OverallParms['Controls'],'publ') #insert the publication template
                # ``template_publ.cif`` or a modified version
                # overall info
                WriteCIFitem(self.fp, 'data_'+str(self.CIFname)+'_overall')
                WriteOverall('seq')
                hist = self.powderDict[sorted(self.powderDict.keys())[0]]
                instnam = self.Histograms[hist]["Sample Parameters"]['InstrName']
                writeCIFtemplate(self.seqSmplParms,'powder',instnam) # powder template
                instnam = instnam.replace(' ','')
                #============================================================
                if phaseWithHist:
                    WriteCIFitem(self.fp, '# POINTERS TO HISTOGRAM BLOCKS (Phase in histogram block)')
                else:
                    WriteCIFitem(self.fp, '# POINTERS TO HISTOGRAM BLOCKS (Phases pointer in histogram block)') 
                datablockidDict = {} # save block names here
                # loop over data blocks
                if len(self.powderDict) + len(self.xtalDict) > 1:
                    loopprefix = ''
                    WriteCIFitem(self.fp, 'loop_   _pd_block_diffractogram_id')
                else:
                    loopprefix = '_pd_block_diffractogram_id'
                for i in sorted(self.powderDict.keys()):
                    hist = self.powderDict[i]
                    j = self.Histograms[hist]['hId']
                    datablockidDict[hist] = (str(self.CIFdate) + "|" + str(self.CIFname) + "|" +
                                             str(self.shortauthorname) + "|" +
                                             instnam + "_hist_"+str(j))
                    WriteCIFitem(self.fp, loopprefix,datablockidDict[hist])
                for i in sorted(self.xtalDict.keys()):
                    hist = self.xtalDict[i]
                    histblk = self.Histograms[hist]
                    instnam = histblk["Instrument Parameters"][0]['InstrName']
                    instnam = instnam.replace(' ','')
                    i = histblk['hId']
                    datablockidDict[hist] = (str(self.CIFdate) + "|" + str(self.CIFname) + "|" +
                                             str(self.shortauthorname) + "|" +
                                             instnam + "_hist_"+str(i))
                    WriteCIFitem(self.fp, loopprefix,datablockidDict[hist])
                # setup and show sequential results table
                tblLabels,tblValues,tblSigs,tblTypes = mkSeqResTable('cif',seqHistList,self.seqData,
                                                    self.Phases,self.Histograms,self.Controls)
                WriteCIFitem(self.fp, '\n# Sequential results table') # (in case anyone can make sense of it)
                WriteCIFitem(self.fp, 'loop_   _gsas_seq_results_col_num _gsas_seq_results_col_label')
                for i,lbl in enumerate(tblLabels):
                    s = PutInCol(str(i),5)
                    if ' ' in lbl:
                        s += '"' + lbl + '"'
                    else:
                        s += lbl
                    WriteCIFitem(self.fp,"  "+s)
                s = 'loop_ '
                linelength = 120
                for i in range(len(tblLabels)):
                    if len(s) > linelength:
                        WriteCIFitem(self.fp,s)
                        s = '  '
                    s += " _gsas_seq_results_val" + str(i)
                WriteCIFitem(self.fp,s)
                
                for r in range(len(tblValues[0])):
                    s = ''
                    for c in range(len(tblLabels)):
                        if len(s) > linelength:
                            WriteCIFitem(self.fp,s)
                            s = '  '
                        sig = None
                        if tblSigs[c] is not None:
                            sig = tblSigs[c][r]
                            
                        if tblValues[c][r] is None:
                            if tblTypes[c] == 'int':
                                wid = 5
                            elif tblTypes[c] == 'str':
                                wid = 10
                            else:
                                wid = 12                               
                            s += PutInCol('.',wid)
                        elif sig is None and ',' in tblTypes[c]:
                            s += PutInCol(
                                ('{{:{}.{}f}}'.format(*tblTypes[c].split(','))).format(tblValues[c][r]),12)
                        elif tblTypes[c] == 'int':
                            s += PutInCol(str(tblValues[c][r]),5)
                        elif tblTypes[c] == 'str':
                            s += PutInCol(str(tblValues[c][r]),10)
                        elif sig is None and ',' in tblTypes[c]:
                            s += PutInCol(
                                ('{{:{}.{}f}}'.format(*tblTypes[c].split(','))).format(tblValues[c][r]),12)
                        elif sig is None and tblTypes[c] == 'float':
                            s += PutInCol('{:.6g}'.format(tblValues[c][r]),12)
                        elif sig:
                            s += PutInCol(G2mth.ValEsd(tblValues[c][r],sig),12)
                        else:
                            s += PutInCol(str(tblValues[c][r]),15)
                    WriteCIFitem(self.fp,s+'\n')

                # sample template info & info for all phases

                i = sorted(self.powderDict.keys())[0]
                hist = self.powderDict[i]
                histblk = self.Histograms[hist]
                if phaseWithHist:    # include sample info in overall block
                    phasenam = list(self.Phases.keys())[0]
                    writeCIFtemplate(self.Phases[phasenam]['General'],'phase',phasenam) # write phase template
                    WriteSeqOverallPhaseInfo(phasenam,histblk)
                else:
                    for j,phasenam in enumerate(sorted(self.Phases.keys())):
                        pId = self.Phases[phasenam]['pId']
                        WriteCIFitem(self.fp, '\n#'+78*'=')
                        WriteCIFitem(self.fp, 'data_'+self.CIFname+"_overall_phase"+str(j)+'\n')
                        writeCIFtemplate(self.Phases[phasenam]['General'],'phase',phasenam) # write phase template
                        WriteSeqOverallPhaseInfo(phasenam,histblk)
                        
                for i in sorted(self.powderDict.keys()):
                    hist = self.powderDict[i]
                    hId = self.Histograms[hist]['hId']
                    dlg.Update(step,"Exporting "+hist.strip())
                    histblk = self.Histograms[hist]
                    WriteCIFitem(self.fp, '# Information for histogram '+str(i)+': '+hist)
                    WriteCIFitem(self.fp, '\ndata_'+self.CIFname+"_pwd_"+str(i))
                    WriteCIFitem(self.fp, '_pd_block_id',datablockidDict[hist])
                    if not phaseWithHist:
                        WriteCIFitem(self.fp, '\n# POINTERS TO PHASE BLOCKS')
                        phaseBlockName = {}

                        wtFrSum = 0.
                        for j,phasenam in enumerate(sorted(self.Phases.keys())):
                            if hist not in self.Phases[phasenam]['Histograms']: continue
                            if not self.Phases[phasenam]['Histograms'][hist]['Use']: continue
                            phFrac = self.Phases[phasenam]['Histograms'][hist]['Scale'][0]
                            phFracKey = str(self.Phases[phasenam]['pId'])+':'+str(hId)+':Scale'
                            phFrac = self.seqData[hist]['parmDict'].get(phFracKey,phFrac)
                            wtFrSum += phFrac * self.Phases[phasenam]['General']['Mass']
                        WriteCIFitem(self.fp, 'loop_ _pd_phase_id _pd_phase_block_id _pd_phase_mass_%')
                        for j,phasenam in enumerate(sorted(self.Phases.keys())):
                            pId = self.Phases[phasenam]['pId']
                            if hist not in self.Phases[phasenam]['Histograms']: continue
                            if not self.Phases[phasenam]['Histograms'][hist]['Use']: continue
                            if ' ' in phasenam:
                                s = PutInCol('"'+phasenam+'"',20)
                            else:
                                s = PutInCol(phasenam,20)
                            phaseBlockName[pId] = datablockidDict[hist]+'_p'+str(j+1)
                            phFrac = self.Phases[phasenam]['Histograms'][hist]['Scale'][0]
                            phFracKey = str(self.Phases[phasenam]['pId'])+':'+str(hId)+':Scale'
                            phFrac = self.seqData[hist]['parmDict'].get(phFracKey,phFrac)
                            wtFr = phFrac * self.Phases[phasenam]['General']['Mass'] / wtFrSum
                            if phFracKey in self.seqData[hist]['varyList']:
                                sig = self.seqData[hist]['sig'][self.seqData[hist]['varyList'].index(phFracKey)]
                                sig *= self.Phases[phasenam]['General']['Mass'] / wtFrSum
                            elif phFracKey in self.seqData[hist]['depParmDict']:
                                sig = self.seqData[hist]['depParmDict'][phFracKey][1]
                                sig *= self.Phases[phasenam]['General']['Mass'] / wtFrSum
                            else:
                                sig = -0.0001
                            WriteCIFitem(self.fp, "  "+ s + " " + phaseBlockName[pId] + "  " + G2mth.ValEsd(wtFr,sig))
                        PP = FormatInstProfile(histblk["Instrument Parameters"],histblk['hId'])
                        PP += '\n'
                        WriteCIFitem(self.fp, '_pd_proc_ls_profile_function',PP)
                
                    WritePowderData(hist,seq=True) # write background, data & reflections, some instrument & sample terms
                    WriteCIFitem(self.fp, '\n# PHASE INFO FOR HISTOGRAM '+hist)
                    for j,phasenam in enumerate(sorted(self.Phases.keys())):
                        pId = self.Phases[phasenam]['pId']
                        if hist not in self.Phases[phasenam]['Histograms']: continue
                        if not self.Phases[phasenam]['Histograms'][hist]['Use']: continue
                        WriteCIFitem(self.fp, '\n# phase info for '+str(phasenam) + ' follows')
                        if not phaseWithHist:
                            WriteCIFitem(self.fp, 'data_'+self.CIFname+"_hist"+str(i)+"_phase"+str(j))
                            WriteCIFitem(self.fp, '_pd_block_id',phaseBlockName[pId])
                            WriteCIFitem(self.fp, '')

                        WriteSeqPhaseVals(phasenam,self.Phases[phasenam],pId,hist)

                        # preferred orientation & profile terms
                        if self.ifPWDR:
                            #SH = FormatSH(phasenam)     # TODO: needs to use seqData
                            #MD = FormatHAPpo(phasenam)  # TODO: switch to seqData
                            #if SH and MD:
                            #    WriteCIFitem(self.fp, '_pd_proc_ls_pref_orient_corr', SH + '\n' + MD)
                            #elif SH or MD:
                            #    WriteCIFitem(self.fp, '_pd_proc_ls_pref_orient_corr', SH + MD)
                            #else:
                            #    WriteCIFitem(self.fp, '_pd_proc_ls_pref_orient_corr', 'none')
                            # report sample profile terms for all histograms with current phase
                            if phaseWithHist:
                                PP = FormatInstProfile(histblk["Instrument Parameters"],histblk['hId'])
                                PP += '\n'
                            else:
                                PP = ''
                            PP += FormatPhaseProfile(phasenam,hist)
                            WriteCIFitem(self.fp, '\n_pd_proc_ls_profile_function',PP)
            finally:
                dlg.Destroy()
        else:
            #---- multiblock: multiple phases and/or histograms ====================
            for phasenam in sorted(self.Phases.keys()):
                rId = phasedict['ranId']
                if rId in self.CellHistSelection: continue
                self.CellHistSelection[rId] = self._CellSelectHist(phasenam)
            nsteps = 1 + len(self.Phases) + len(self.powderDict) + len(self.xtalDict)
            dlg = wx.ProgressDialog('CIF progress','starting',nsteps,parent=self.G2frame)
            dlg.CenterOnParent()

            # publication info
            step = 1
            dlg.Update(step,"Exporting overall section")
            WriteCIFitem(self.fp, '\ndata_'+self.CIFname+'_publ')
            WriteAudit()
            WriteCIFitem(self.fp, '_pd_block_id',
                         str(self.CIFdate) + "|" + str(self.CIFname) + "|" +
                         str(self.shortauthorname) + "|Overall")
            writeCIFtemplate(self.OverallParms['Controls'],'publ') #insert the publication template
            # ``template_publ.cif`` or a modified version
            # overall info
            WriteCIFitem(self.fp, 'data_'+str(self.CIFname)+'_overall')
            WriteOverall()
            #============================================================
            WriteCIFitem(self.fp, '# POINTERS TO PHASE AND HISTOGRAM BLOCKS')
            datablockidDict = {} # save block names here -- N.B. check for conflicts between phase & hist names (unlikely!)
            # loop over phase blocks
            if len(self.Phases) > 1:
                loopprefix = ''
                WriteCIFitem(self.fp, 'loop_   _pd_phase_block_id')
            else:
                loopprefix = '_pd_phase_block_id'

            for phasenam in sorted(self.Phases.keys()):
                i = self.Phases[phasenam]['pId']
                datablockidDict[phasenam] = (str(self.CIFdate) + "|" + str(self.CIFname) + "|" +
                             'phase_'+ str(i) + '|' + str(self.shortauthorname))
                WriteCIFitem(self.fp, loopprefix,datablockidDict[phasenam])
            # loop over data blocks
            if len(self.powderDict) + len(self.xtalDict) > 1:
                loopprefix = ''
                WriteCIFitem(self.fp, 'loop_   _pd_block_diffractogram_id')
            else:
                loopprefix = '_pd_block_diffractogram_id'
            for i in sorted(self.powderDict.keys()):
                hist = self.powderDict[i]
                histblk = self.Histograms[hist]
                instnam = histblk["Sample Parameters"]['InstrName']
                instnam = instnam.replace(' ','')
                j = histblk['hId']
                datablockidDict[hist] = (str(self.CIFdate) + "|" + str(self.CIFname) + "|" +
                                         str(self.shortauthorname) + "|" +
                                         instnam + "_hist_"+str(j))
                WriteCIFitem(self.fp, loopprefix,datablockidDict[hist])
            for i in sorted(self.xtalDict.keys()):
                hist = self.xtalDict[i]
                histblk = self.Histograms[hist]
                instnam = histblk["Instrument Parameters"][0]['InstrName']
                instnam = instnam.replace(' ','')
                i = histblk['hId']
                datablockidDict[hist] = (str(self.CIFdate) + "|" + str(self.CIFname) + "|" +
                                         str(self.shortauthorname) + "|" +
                                         instnam + "_hist_"+str(i))
                WriteCIFitem(self.fp, loopprefix,datablockidDict[hist])
            #============================================================
            # loop over phases, exporting them
            for j,phasenam in enumerate(sorted(self.Phases.keys())):
                step += 1
                dlg.Update(step,"Exporting phase "+phasenam+' (#'+str(j+1)+')')
                i = self.Phases[phasenam]['pId']
                WriteCIFitem(self.fp, '\ndata_'+self.CIFname+"_phase_"+str(i))
                WriteCIFitem(self.fp, '# Information for phase '+str(i))
                WriteCIFitem(self.fp, '_pd_block_id',datablockidDict[phasenam])
                # report the phase
                writeCIFtemplate(self.Phases[phasenam]['General'],'phase',phasenam) # write phase template
                WritePhaseInfo(phasenam,False,False)
                # preferred orientation
                if self.ifPWDR:
                    SH = FormatSH(phasenam)
                    MD = FormatHAPpo(phasenam)
                    if SH and MD:
                        WriteCIFitem(self.fp, '_pd_proc_ls_pref_orient_corr', SH + '\n' + MD)
                    elif SH or MD:
                        WriteCIFitem(self.fp, '_pd_proc_ls_pref_orient_corr', SH + MD)
                    else:
                        WriteCIFitem(self.fp, '_pd_proc_ls_pref_orient_corr', 'none')
                # report sample profile terms for all histograms with current phase
                PP = FormatPhaseProfile(phasenam)
                if PP:
                    WriteCIFitem(self.fp, '_pd_proc_ls_profile_function',PP)
                self.ShowHstrainCells(phasenam,datablockidDict)

            #============================================================
            # loop over histograms, exporting them
            # first, get atoms across all phases
            uniqueAtoms = []
            for phasenam in self.Phases:
                cx,ct,cs,cia = self.Phases[phasenam]['General']['AtomPtrs']
                for line in self.Phases[phasenam]['Atoms']:
                    atype = line[ct].strip()
                    if atype.find('-') != -1: atype = atype.split('-')[0]
                    if atype.find('+') != -1: atype = atype.split('+')[0]
                    atype = atype[0].upper()+atype[1:2].lower() # force case conversion
                    if atype == "D" or atype == "D": atype = "H"
                    if atype not in uniqueAtoms:
                        uniqueAtoms.append(atype)

            for i in sorted(self.powderDict.keys()):
                hist = self.powderDict[i]
                histblk = self.Histograms[hist]
                if hist.startswith("PWDR"):
                    step += 1
                    dlg.Update(step,"Exporting "+hist.strip())
                    WriteCIFitem(self.fp, '\ndata_'+self.CIFname+"_pwd_"+str(i))
                    WriteCIFitem(self.fp, '# Information for histogram '+str(i)+': '+hist)
                    #instnam = histblk["Sample Parameters"]['InstrName']
                    # report instrumental profile terms
                    WriteCIFitem(self.fp, '_pd_proc_ls_profile_function',
                        FormatInstProfile(histblk["Instrument Parameters"],histblk['hId']))
                    WriteCIFitem(self.fp, '_pd_block_id',datablockidDict[hist])
                    histprm = self.Histograms[hist]["Sample Parameters"]
                    writeCIFtemplate(histprm,'powder',histprm['InstrName']) # powder template
                    
                    # get xray wavelength and compute & write f' & f''
                    lam = None
                    if 'X' in histblk['Instrument Parameters'][0]['Type'][0]:
                        for k in ('Lam','Lam1'):
                            if k in histblk['Instrument Parameters'][0]:
                                lam = histblk['Instrument Parameters'][0][k][0]
                                break
                    if lam:
                        keV = 12.397639/lam
                        WriteCIFitem(self.fp,'loop_')
                        for item in ('_atom_type_symbol','_atom_type_scat_dispersion_real',
                                         '_atom_type_scat_dispersion_imag','_atom_type_scat_dispersion_source'):
                            WriteCIFitem(self.fp,'     '+item)
                        for elem in HillSortElements(uniqueAtoms):
                            s = '  '
                            s += PutInCol(elem,4)
                            Orbs = G2el.GetXsectionCoeff(elem)
                            FP,FPP,Mu = G2el.FPcalc(Orbs, keV)
                            s += '  {:8.3f}{:8.3f}   https://subversion.xray.aps.anl.gov/pyGSAS/trunk/atmdata.py'.format(FP,FPP)
                            WriteCIFitem(self.fp,s.rstrip())
                        WriteCIFitem(self.fp,'')
                    WritePowderData(hist)
            for i in sorted(self.xtalDict.keys()):
                hist = self.xtalDict[i]
                histblk = self.Histograms[hist]
                if hist.startswith("HKLF"):
                    step += 1
                    dlg.Update(step,"Exporting "+hist.strip())
                    WriteCIFitem(self.fp, '\ndata_'+self.CIFname+"_sx_"+str(i))
                    #instnam = histblk["Instrument Parameters"][0]['InstrName']
                    WriteCIFitem(self.fp, '# Information for histogram '+str(i)+': '+hist)
                    WriteCIFitem(self.fp, '_pd_block_id',datablockidDict[hist])
                    histprm = self.Histograms[hist]["Instrument Parameters"][0]
                    writeCIFtemplate(histprm,'single',histprm['InstrName']) # single crystal template
                    WriteSingleXtalData(hist)

            dlg.Destroy()

        WriteCIFitem(self.fp, '#--' + 15*'eof--' + '#')
        print("...export completed")
        print('file '+self.fullpath)
        # end of CIF export

class ExportProjectCIF(ExportCIF):
    '''Used to create a CIF of an entire project

    :param wx.Frame G2frame: reference to main GSAS-II frame
    '''
    def __init__(self,G2frame):
        ExportCIF.__init__(self,
            G2frame=G2frame,
            formatName = 'Full CIF',
            extension='.cif',
            longFormatName = 'Export project as CIF'
            )
        self.exporttype = ['project']

    def Exporter(self,event=None,seqData=None,Controls=None):
        self.seqData = seqData
        self.Controls = Controls
        self.InitExport(event)
        # load all of the tree into a set of dicts
        self.loadTree()
        self._Exporter(event=event)
        self.CloseFile()

class ExportPhaseCIF(ExportCIF):
    '''Used to create a simple CIF with one phase. Uses exact same code as
    :class:`ExportCIF` except that `phaseOnly` is set for the Exporter
    Shows up in menu as Quick CIF.

    :param wx.Frame G2frame: reference to main GSAS-II frame
    '''
    def __init__(self,G2frame):
        ExportCIF.__init__(self,
            G2frame=G2frame,
            formatName = 'Quick CIF',
            extension='.cif',
            longFormatName = 'Export one phase in CIF'
            )
        self.exporttype = ['phase']
        # CIF-specific items
        self.author = ''

    def Exporter(self,event=None):
        # get a phase and file name
        # the export process starts here
        self.InitExport(event)
        # load all of the tree into a set of dicts
        self.loadTree()
        # create a dict with refined values and their uncertainties
        self.loadParmDict()
        self.multiple = True
        self.currentExportType = 'phase'
        if self.ExportSelect('ask'): return
        self.OpenFile()
        for name in self.phasenam:
            self._Exporter(event=event,phaseOnly=name)  #TODO: repeat for magnetic phase
        self.CloseFile()

    def Writer(self,hist,phasenam,mode='w'):
        # set the project file name
        self.CIFname = os.path.splitext(
            os.path.split(self.G2frame.GSASprojectfile)[1]
            )[0]+'_'+phasenam+'_'+hist
        self.CIFname = self.CIFname.replace(' ','')
        self.OpenFile(mode=mode)
        self._Exporter(phaseOnly=phasenam)
        self.CloseFile()

class ExportPwdrCIF(ExportCIF):
    '''Used to create a simple CIF containing diffraction data only. Uses exact same code as
    :class:`ExportCIF` except that `histOnly` is set for the Exporter
    Shows up in menu as Quick CIF.

    :param wx.Frame G2frame: reference to main GSAS-II frame
    '''
    def __init__(self,G2frame):
        ExportCIF.__init__(self,
            G2frame=G2frame,
            formatName = 'Data-only CIF',
            extension='.cif',
            longFormatName = 'Export data as CIF'
            )
        if G2frame is None: raise AttributeError('CIF export requires data tree') # prevent use from Scriptable
        self.exporttype = ['powder']
        # CIF-specific items
        self.author = ''

    def Exporter(self,event=None):
        self.InitExport(event)
        # load all of the tree into a set of dicts
        self.currentExportType = None
        self.loadTree()
        self.currentExportType = 'powder'
        # create a dict with refined values and their uncertainties
        self.loadParmDict()
        self.multiple = False
        if self.ExportSelect( # set export parameters
            AskFile='ask' # get a file name/directory to save in
            ): return
        self.OpenFile()
        self._Exporter(event=event,histOnly=self.histnam[0])

    def Writer(self,hist,mode='w'):
        '''Used for histogram CIF export of a sequential fit.
        '''
        # set the project file name
        self.CIFname = os.path.splitext(
            os.path.split(self.G2frame.GSASprojectfile)[1]
            )[0]+'_'+hist
        self.CIFname = self.CIFname.replace(' ','')
        self.OpenFile(mode=mode)
        self._Exporter(histOnly=hist)
        if mode == 'w':
            print('CIF written to file '+self.fullpath)
        self.CloseFile()

class ExportHKLCIF(ExportCIF):
    '''Used to create a simple CIF containing diffraction data only. Uses exact same code as
    :class:`ExportCIF` except that `histOnly` is set for the Exporter
    Shows up in menu as Quick CIF.

    :param wx.Frame G2frame: reference to main GSAS-II frame
    '''
    def __init__(self,G2frame):
        ExportCIF.__init__(self,
            G2frame=G2frame,
            formatName = 'Data-only CIF',
            extension='.cif',
            longFormatName = 'Export data as CIF'
            )
        self.exporttype = ['single']
        # CIF-specific items
        self.author = ''

    def Exporter(self,event=None):
        self.InitExport(event)
        # load all of the tree into a set of dicts
        self.currentExportType = None
        self.loadTree()
        self.currentExportType = 'single'
        # create a dict with refined values and their uncertainties
        self.loadParmDict()
        self.multiple = False
        if self.ExportSelect( # set export parameters
            AskFile='ask' # get a file name/directory to save in
            ): return
        self.OpenFile()
        self._Exporter(event=event,histOnly=self.histnam[0])

#===============================================================================
# misc CIF utilities
#===============================================================================
def PickleCIFdict(fil):
    '''Loads a CIF dictionary, cherry picks out the items needed
    by local code and sticks them into a python dict and writes
    that dict out as a pickle file for later reuse.
    If the write fails a warning message is printed,
    but no exception occurs.

    :param str fil: file name of CIF dictionary, will usually end
      in .dic
    :returns: the dict with the definitions
    '''
    import CifFile as cif # PyCifRW from James Hester
    cifdic = {}
    try:
        fp = open(fil,'r')             # patch: open file to avoid windows bug
        dictobj = cif.CifDic(fp)
        fp.close()
    except IOError:
        dictobj = cif.CifDic(fil)
    if DEBUG: print('loaded '+fil)
    for item in dictobj.keys():
        cifdic[item] = {}
        for j in (
            '_definition','_type',
            '_enumeration',
            '_enumeration_detail',
            '_enumeration_range'):
            if dictobj[item].get(j):
                cifdic[item][j] = dictobj[item][j]
    try:
        fil = os.path.splitext(fil)[0]+'.cpickle'
        fp = open(fil,'wb')
        pickle.dump(cifdic,fp)
        fp.close()
        if DEBUG: print('wrote '+fil)
    except:
        print ('Unable to write '+fil)
    return cifdic

def LoadCIFdic():
    '''Create a composite core+powder CIF lookup dict containing
    information about all items in the CIF dictionaries, loading
    pickled files if possible. The routine looks for files
    named cif_core.cpickle and cif_pd.cpickle in every
    directory in the path and if they are not found, files
    cif_core.dic and/or cif_pd.dic are read.

    :returns: the dict with the definitions
    '''
    cifdic = {}
    for ftyp in "cif_core","cif_pd":
        for loc in sys.path:
            fil = os.path.join(loc,ftyp+".cpickle")
            if not os.path.exists(fil): continue
            fp = open(fil,'rb')
            try:
                cifdic.update(pickle.load(fp))
                if DEBUG: print('reloaded '+fil)
                break
            finally:
                fp.close()
        else:
            for loc in sys.path:
                fil = os.path.join(loc,ftyp+".dic")
                if not os.path.exists(fil): continue
                #try:
                if True:
                    cifdic.update(PickleCIFdict(fil))
                    break
                #except:
                #    pass
            else:
                print('Could not load '+ftyp+' dictionary')
    return cifdic

class CIFdefHelp(wx.Button):
    '''Create a help button that displays help information on
    the current data item

    :param parent: the panel which will be the parent of the button
    :param str msg: the help text to be displayed
    :param wx.Dialog helpwin: Frame for CIF editing dialog
    :param wx.TextCtrl helptxt: TextCtrl where help text is placed
    '''
    def __init__(self,parent,msg,helpwin,helptxt):
        wx.Button.__init__(self,parent,wx.ID_HELP)
        self.Bind(wx.EVT_BUTTON,self._onPress)
        self.msg=msg
        self.parent = parent
        self.helpwin = helpwin
        self.helptxt = helptxt
    def _onPress(self,event):
        'Respond to a button press by displaying the requested text'
        try:
            ww,wh = self.helpwin.GetSize()
            ow,oh = self.helptxt.GetSize()
            self.helptxt.SetLabel(self.msg)
            self.helptxt.Wrap(ww-10)
            w,h = self.helptxt.GetSize()
            if h > oh: # resize the help area if needed, but avoid changing width
                self.helptxt.SetMinSize((ww,h))
                self.helpwin.GetSizer().Fit(self.helpwin)
        except: # error posting help, ignore
            return

def CIF2dict(cf):
    '''copy the contents of a CIF out from a PyCifRW block object
    into a dict

    :returns: cifblk, loopstructure where cifblk is a dict with
      CIF items and loopstructure is a list of lists that defines
      which items are in which loops.
    '''
    blk = cf.keys()[0] # assume templates are a single CIF block, use the 1st
    try:
        loopstructure = cf[blk].loopnames()[:] # copy over the list of loop contents
    except AttributeError:
        loopstructure = [j[:] for j in cf[blk].loops.values()] # method replaced?
    dblk = {}
    for item in cf[blk].keys(): # make a copy of all the items in the block
        dblk[item] = cf[blk][item]
    return dblk,loopstructure

def dict2CIF(dblk,loopstructure,blockname='Template'):
    '''Create a PyCifRW CIF object containing a single CIF
    block object from a dict and loop structure list.

    :param dblk: a dict containing values for each CIF item
    :param list loopstructure: a list of lists containing the contents of
      each loop, as an example::

         [ ["_a","_b"], ["_c"], ["_d_1","_d_2","_d_3"]]

      this describes a CIF with this type of structure::

        loop_ _a _b <a1> <b1> <a2> ...
        loop_ _c <c1> <c2>...
        loop _d_1 _d_2 _d_3 ...

      Note that the values for each looped CIF item, such as _a,
      are contained in a list, for example as cifblk["_a"]

    :param str blockname: an optional name for the CIF block.
      Defaults to 'Template'

    :returns: the newly created PyCifRW CIF object
    '''

    import CifFile as cif # PyCifRW from James Hester
    # compile a 'list' of items in loops
    loopnames = set()
    for i in loopstructure:
        loopnames |= set(i)
    # create a new block
    newblk = cif.CifBlock()
    # add the looped items
    for keys in loopstructure:
        vals = []
        for key in keys:
            vals.append(dblk[key])
        newblk.AddCifItem(([keys],[vals]))
    # add the non-looped items
    for item in dblk:
        if item in loopnames: continue
        newblk[item] = dblk[item]
    # create a CIF and add the block
    newcf = cif.CifFile()
    newcf[blockname] = newblk
    return newcf


class EditCIFtemplate(wx.Dialog):
    '''Create a dialog for editing a CIF template. The edited information is
    placed in cifblk. If the CIF is saved as a file, the name of that file
    is saved as ``self.newfile``.

    :param wx.Frame parent: parent frame or None
    :param cifblk: dict or PyCifRW block containing values for each CIF item
    :param list loopstructure: a list of lists containing the contents of
      each loop, as an example::

         [ ["_a","_b"], ["_c"], ["_d_1","_d_2","_d_3"]]

      this describes a CIF with this type of structure::

        loop_ _a _b <a1> <b1> <a2> ...
        loop_ _c <c1> <c2>...
        loop _d_1 _d_2 _d_3 ...

      Note that the values for each looped CIF item, such as _a,
      are contained in a list, for example as cifblk["_a"]

    :param str defaultname: specifies the default file name to be used for
      saving the CIF.
    '''
    def __init__(self,parent,cifblk,loopstructure,defaultname):
        OKbuttons = []
        self.cifblk = cifblk
        self.loopstructure = loopstructure
        self.newfile = None
        self.defaultname = defaultname
        self.G2frame = parent.G2frame
        global CIFdic  # once this is loaded, keep it around
        if CIFdic is None:
            CIFdic = LoadCIFdic()
        wx.Dialog.__init__(self,parent,style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)

        # define widgets that will be needed during panel creation
        self.helptxt = wx.StaticText(self,wx.ID_ANY,"")
        savebtn = wx.Button(self, wx.ID_CLOSE, "Save as template")
        OKbuttons.append(savebtn)
        savebtn.Bind(wx.EVT_BUTTON,self._onSave)
        OKbtn = wx.Button(self, wx.ID_OK, "Use")
        OKbtn.Bind(wx.EVT_BUTTON, lambda x: self.EndModal(wx.ID_OK))
        OKbtn.SetDefault()
        OKbuttons.append(OKbtn)

        self.SetTitle('Edit items in CIF template')
        vbox = wx.BoxSizer(wx.VERTICAL)
        cpnl = EditCIFpanel(self,cifblk,loopstructure,CIFdic,OKbuttons,size=(300,300))
        vbox.Add(cpnl, 1, wx.ALIGN_LEFT|wx.ALL|wx.EXPAND, 0)
        G2G.HorizontalLine(vbox,self)
        vbox.Add(self.helptxt, 0, wx.EXPAND|wx.ALL, 5)
        G2G.HorizontalLine(vbox,self)
        btnsizer = wx.BoxSizer(wx.HORIZONTAL)
        btn = wx.Button(self, wx.ID_CANCEL)
        btnsizer.Add(btn,0,wx.ALIGN_CENTER|wx.ALL)
        btnsizer.Add(savebtn,0,wx.ALIGN_CENTER|wx.ALL)
        btnsizer.Add(OKbtn,0,wx.ALIGN_CENTER|wx.ALL)
        vbox.Add(btnsizer, 0, wx.ALIGN_CENTER|wx.ALL, 5)
        self.SetSizer(vbox)
        vbox.Fit(self)
    def Post(self):
        '''Display the dialog

        :returns: True unless Cancel has been pressed.
        '''
        return (self.ShowModal() == wx.ID_OK)
    def _onSave(self,event):
        'Save CIF entries in a template file'
        pth = G2G.GetExportPath(self.G2frame)
        dlg = wx.FileDialog(
            self, message="Save as CIF template",
            defaultDir=pth,
            defaultFile=self.defaultname,
            wildcard="CIF (*.cif)|*.cif",
            style=wx.FD_SAVE)
        val = (dlg.ShowModal() == wx.ID_OK)
        fil = dlg.GetPath()
        dlg.Destroy()
        if val: # ignore a Cancel button
            fil = os.path.splitext(fil)[0]+'.cif' # force extension
            fp = open(fil,'w')
            newcf = dict2CIF(self.cifblk,self.loopstructure)
            fp.write(newcf.WriteOut())
            fp.close()
            self.newfile = fil
            self.EndModal(wx.ID_OK)

class EditCIFpanel(wxscroll.ScrolledPanel):
    '''Creates a scrolled panel for editing CIF template items

    :param wx.Frame parent: parent frame where panel will be placed
    :param cifblk: dict or PyCifRW block containing values for each CIF item
    :param list loopstructure: a list of lists containing the contents of
      each loop, as an example::

         [ ["_a","_b"], ["_c"], ["_d_1","_d_2","_d_3"]]

      this describes a CIF with this type of structure::

        loop_ _a _b <a1> <b1> <a2> ...
        loop_ _c <c1> <c2>...
        loop _d_1 _d_2 _d_3 ...

      Note that the values for each looped CIF item, such as _a,
      are contained in a list, for example as cifblk["_a"]

    :param dict cifdic: optional CIF dictionary definitions
    :param list OKbuttons: A list of wx.Button objects that should
      be disabled when information in the CIF is invalid
    :param (other): optional keyword parameters for wx.ScrolledPanel
    '''
    def __init__(self, parent, cifblk, loopstructure, cifdic={}, OKbuttons=[], **kw):
        self.parent = parent
        wxscroll.ScrolledPanel.__init__(self, parent, wx.ID_ANY, **kw)
        self.vbox = None
        self.AddDict = None
        self.cifdic = cifdic
        self.cifblk = cifblk
        self.loops = loopstructure
        self.parent = parent
        self.LayoutCalled = False
        self.parentOKbuttons = OKbuttons
        self.ValidatedControlsList = []
        self.G2frame = parent.G2frame
        self.height = G2G.getTextSize('?')[1]
        #print('height is ',self.height)
        self._fill()
    def _fill(self):
        'Fill the scrolled panel with widgets for each CIF item'
        wx.BeginBusyCursor()
        self.AddDict = {}
        self.ValidatedControlsList = []
        # delete any only contents
        if self.vbox:
            if 'phoenix' in wx.version():
                self.vbox.Clear(True)
            else:
                self.vbox.DeleteWindows()
            self.vbox = None
            self.Update()
        vbox = wx.BoxSizer(wx.VERTICAL)
        self.vbox = vbox
        # compile a 'list' of items in loops
        loopnames = set()
        for i in self.loops:
            loopnames |= set(i)
        # post the looped CIF items
        for lnum,lp in enumerate(self.loops):
            hbox = wx.BoxSizer(wx.HORIZONTAL)
            hbox.Add(wx.StaticText(self,wx.ID_ANY,'Loop '+str(lnum+1)))
            vbox.Add(hbox)
            but = wx.Button(self,wx.ID_ANY,"Add row")
            self.AddDict[but]=lnum

            hbox.Add(but)
            but.Bind(wx.EVT_BUTTON,self.OnAddRow)
            fbox = wx.GridBagSizer(0, 0)
            vbox.Add(fbox)
            rows = 0
            for i,item in enumerate(lp):
                txt = wx.StaticText(self,wx.ID_ANY,item+"  ")
                fbox.Add(txt,(0,i+1))
                for j,val in enumerate(self.cifblk[item]):
                    ent = self.CIFEntryWidget(self.cifblk[item],j,item)
                    #fbox.Add(ent,(j+2,i+1),flag=wx.EXPAND|wx.ALL)
                    fbox.Add(ent,(j+1,i+1),flag=wx.EXPAND|wx.ALL)
                if self.cifdic.get(item):
                    df = self.cifdic[item].get('_definition')
                    if df:
                        try:
                            txt.SetToolTip(G2IO.trim(df))
                        except:
                            txt.SetToolTipString(G2IO.trim(df))
                        but = CIFdefHelp(self,
                                         "Definition for "+item+":\n\n"+G2IO.trim(df),
                                         self.parent,
                                         self.parent.helptxt)
                        fbox.Add(but,(j+2,i+1),flag=wx.ALIGN_CENTER)
                rows = max(rows,len(self.cifblk[item]))
            for i in range(rows):
                txt = wx.StaticText(self,wx.ID_ANY,str(i+1))
                fbox.Add(txt,(i+1,0))
            line = wx.StaticLine(self,wx.ID_ANY, size=(-1,3), style=wx.LI_HORIZONTAL)
            vbox.Add(line, 0, wx.EXPAND|wx.ALL, 10)

        # post the non-looped CIF items
        for item in sorted(self.cifblk.keys()):
            if item not in loopnames:
                hbox = wx.BoxSizer(wx.HORIZONTAL)
                vbox.Add(hbox)
                txt = wx.StaticText(self,wx.ID_ANY,item)
                hbox.Add(txt)
                ent = self.CIFEntryWidget(self.cifblk,item,item)
                hbox.Add(ent)
                if self.cifdic.get(item):
                    df = self.cifdic[item].get('_definition')
                    if df:
                        try:
                            txt.SetToolTip(G2IO.trim(df))
                        except:
                            txt.SetToolTipString(G2IO.trim(df))
                        but = CIFdefHelp(self,
                                         "Definition for "+item+":\n\n"+G2IO.trim(df),
                                         self.parent,
                                         self.parent.helptxt)
                        hbox.Add(but,0,wx.ALL,2)
        self.SetSizer(vbox)
        #vbox.Fit(self.parent)
        self.SetAutoLayout(1)
        self.SetupScrolling()
        self.Bind(rw.EVT_RW_LAYOUT_NEEDED, self.OnLayoutNeeded)
        self.Layout()
        wx.EndBusyCursor()
    def OnLayoutNeeded(self,event):
        '''Called when an update of the panel layout is needed. Calls
        self.DoLayout after the current operations are complete using
        CallAfter. This is called only once, according to flag
        self.LayoutCalled, which is cleared in self.DoLayout.
        '''
        if self.LayoutCalled: return # call already queued
        wx.CallAfter(self.DoLayout) # queue a call
        self.LayoutCalled = True
    def DoLayout(self):
        '''Update the Layout and scroll bars for the Panel. Clears
        self.LayoutCalled so that next change to panel can
        request a new update
        '''
        wx.BeginBusyCursor()
        self.Layout()
        self.SetupScrolling()
        wx.EndBusyCursor()
        self.LayoutCalled = False
    def OnAddRow(self,event):
        'add a row to a loop'
        lnum = self.AddDict.get(event.GetEventObject())
        if lnum is None: return
        for item in self.loops[lnum]:
            self.cifblk[item].append('?')
        self._fill()

    def ControlOKButton(self,setvalue):
        '''Enable or Disable the OK button(s) for the dialog. Note that this is
        passed into the ValidatedTxtCtrl for use by validators.

        :param bool setvalue: if True, all entries in the dialog are
          checked for validity. The first invalid control triggers
          disabling of buttons.
          If False then the OK button(s) are disabled with no checking
          of the invalid flag for each control.
        '''
        if setvalue: # turn button on, do only if all controls show as valid
            for ctrl in self.ValidatedControlsList:
                if ctrl.invalid:
                    for btn in self.parentOKbuttons:
                        btn.Disable()
                    return
            else:
                for btn in self.parentOKbuttons:
                    btn.Enable()
        else:
            for btn in self.parentOKbuttons:
                btn.Disable()

    def CIFEntryWidget(self,dct,item,dataname):
        '''Create an entry widget for a CIF item. Use a validated entry for numb values
        where int is required when limits are integers and floats otherwise.
        At present this does not allow entry of the special CIF values of "." and "?" for
        numerical values and highlights them as invalid.
        Use a selection widget when there are specific enumerated values for a string.
        '''
        if self.cifdic.get(dataname):
            if self.cifdic[dataname].get('_enumeration'):
                values = ['?']+self.cifdic[dataname]['_enumeration']
                choices = ['undefined']
                for i in self.cifdic[dataname].get('_enumeration_detail',values):
                    choices.append(G2IO.trim(i))
                ent = G2G.EnumSelector(self, dct, item, choices, values, size=(200, -1))
                return ent
            if self.cifdic[dataname].get('_type') == 'numb':
                mn = None
                mx = None
                hint = int
                if self.cifdic[dataname].get('_enumeration_range'):
                    rng = self.cifdic[dataname]['_enumeration_range'].split(':')
                    if '.' in rng[0] or '.' in rng[1]: hint = float
                    if rng[0]: mn = hint(rng[0])
                    if rng[1]: mx = hint(rng[1])
                    ent = G2G.ValidatedTxtCtrl(
                        self,dct,item,typeHint=hint,xmin=mn,xmax=mx,
                        CIFinput=True,ASCIIonly=True,
                        OKcontrol=self.ControlOKButton)
                    self.ValidatedControlsList.append(ent)
                    return ent
        rw1 = rw.ResizeWidget(self)
        ent = G2G.ValidatedTxtCtrl(
            rw1,dct,item,size=(100, self.height+5),
            style=wx.TE_MULTILINE|wx.TE_PROCESS_ENTER,
            CIFinput=True,ASCIIonly=True,
            OKcontrol=self.ControlOKButton)
        self.ValidatedControlsList.append(ent)
        return rw1

class CIFtemplateSelect(wx.BoxSizer):
    '''Create a set of buttons to show, select and edit a CIF template

    :param frame: wx.Frame object of parent
    :param panel: wx.Panel object where widgets should be placed
    :param str tmplate: one of 'publ', 'phase', or 'instrument' to determine
      the type of template
    :param dict G2dict: GSAS-II dict where CIF should be placed. The key
      "CIF_template" will be used to store either a list or a string.
      If a list, it will contain a dict and a list defining loops. If
      an str, it will contain a file name.
    :param function repaint: reference to a routine to be called to repaint
      the frame after a change has been made
    :param str title: A line of text to show at the top of the window
    :param str defaultname: specifies the default file name to be used for
      saving the CIF.
    '''
    def __init__(self,frame,panel,tmplate,G2dict, repaint, title, defaultname=''):
        wx.BoxSizer.__init__(self,wx.VERTICAL)
        self.cifdefs = frame
        self.dict = G2dict
        self.repaint = repaint
        self.G2frame = frame.G2frame
        templateDefName = 'template_'+tmplate+'.cif'
        self.CIF = G2dict.get("CIF_template")
        if defaultname:
            self.defaultname = G2obj.StripUnicode(defaultname)
            self.defaultname = re.sub(r'[^a-zA-Z0-9_-]','',self.defaultname)
            self.defaultname = tmplate + "_" + self.defaultname + ".cif"
        else:
            self.defaultname = ''

        txt = wx.StaticText(panel,wx.ID_ANY,title)
        self.Add(txt,0,wx.ALIGN_CENTER)
        # change font on title
        txtfnt = txt.GetFont()
        txtfnt.SetWeight(wx.BOLD)
        txtfnt.SetPointSize(2+txtfnt.GetPointSize())
        txt.SetFont(txtfnt)
        self.Add((-1,3))

        if not self.CIF: # empty or None
            for pth in [os.getcwd()]+sys.path:
                fil = os.path.join(pth,self.defaultname)
                if os.path.exists(fil) and self.defaultname:
                    self.CIF = fil
                    CIFtxt = "Template: "+self.defaultname
                    break
            else:
                for pth in sys.path:
                    fil = os.path.join(pth,templateDefName)
                    if os.path.exists(fil):
                        self.CIF = fil
                        CIFtxt = "Template: "+templateDefName
                        break
                else:
                    print("Default CIF template "+self.defaultname+' not found in path!')
                    self.CIF = None
                    CIFtxt = "none! (No template found)"
        elif type(self.CIF) is not list and type(self.CIF) is not tuple:
            if not os.path.exists(self.CIF):
                print("Error: template file has disappeared: "+self.CIF)
                self.CIF = None
                CIFtxt = "none! (file not found)"
            else:
                if len(self.CIF) < 50:
                    CIFtxt = "File: "+self.CIF
                else:
                    CIFtxt = "File: ..."+self.CIF[-50:]
        else:
            CIFtxt = "Template is customized"
        # show template source
        self.Add(wx.StaticText(panel,wx.ID_ANY,CIFtxt))
        # show str, button to select file; button to edit (if CIF defined)
        but = wx.Button(panel,wx.ID_ANY,"Select Template File")
        but.Bind(wx.EVT_BUTTON,self._onGetTemplateFile)
        hbox =  wx.BoxSizer(wx.HORIZONTAL)
        hbox.Add(but,0,0,2)
        but = wx.Button(panel,wx.ID_ANY,"Edit Template")
        but.Bind(wx.EVT_BUTTON,self._onEditTemplateContents)
        if self.CIF is None: but.Disable() # nothing to edit!
        hbox.Add(but,0,0,2)
        self.Add(hbox)
    def _onGetTemplateFile(self,event):
        'select a template file'
        pth = G2G.GetImportPath(self.G2frame)
        if not pth: pth = '.'
        dlg = wx.FileDialog(
            self.cifdefs, message="Read CIF template file",
            defaultDir=pth,
            defaultFile=self.defaultname,
            wildcard="CIF (*.cif)|*.cif",
            style=wx.FD_OPEN)
        ret = dlg.ShowModal()
        fil = dlg.GetPath()
        dlg.Destroy()
        if ret == wx.ID_OK:
            cf = G2obj.ReadCIF(fil)
            if len(cf.keys()) == 0:
                raise Exception("No CIF data_ blocks found")
            if len(cf.keys()) != 1:
                raise Exception('Error, CIF Template has more than one block: '+fil)
            self.dict["CIF_template"] = fil
            self.repaint() #EditCIFDefaults()

    def _onEditTemplateContents(self,event):
        'Called to edit the contents of a CIF template'
        if type(self.CIF) is list or  type(self.CIF) is tuple:
            dblk,loopstructure = copy.deepcopy(self.CIF) # don't modify original
        else:
            cf = G2obj.ReadCIF(self.CIF)
            dblk,loopstructure = CIF2dict(cf)
        dlg = EditCIFtemplate(self.cifdefs,dblk,loopstructure,self.defaultname)
        val = dlg.Post()
        if val:
            if dlg.newfile: # results saved in file
                self.dict["CIF_template"] = dlg.newfile
            else:
                self.dict["CIF_template"] = [dlg.cifblk,dlg.loopstructure]
            self.repaint() #EditCIFDefaults() # note that this does a dlg.Destroy()
        else:
            dlg.Destroy()

#===============================================================================
# end of misc CIF utilities
#===============================================================================
